from fastapi import Depends, FastAPI, Header, UploadFile, File, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing import Any, Literal

from email_verifier.verifier import verify_email_list
from services.csv_reader import CSVReader
from services.csv_cleaner import CSVCleaner

from settings.config import EMAIL_CONFIG, EMAIL_PROVIDER
from email_sender.sender import EmailSender
from campaigns.bulk_sender import BulkSender
from services.transactional_email import (
    TransactionalEmailError,
    build_message,
    decode_attachments,
    html_to_text,
)
from services.tenant_store import TenantStore, TenantStoreError
from services.ai_content import AIContentError, generate_email_draft, generate_signature_draft
from services.deliverability import analyze_email
from services.campaigns import normalize_contacts, render_campaign
from services.recipient_name import recipient_variables
from services.contact_csv import ContactCSVError, parse_contacts_csv
from services.redis_queue import RedisQueueError, TransactionalQueue, utc_now
from services.dashboard_auth import create_session, verify_password, verify_session

import shutil
import os
import secrets
import time
import hmac
import threading


TRANSACTIONAL_QUEUE_BATCH_SIZE = int(os.getenv("TRANSACTIONAL_BATCH_SIZE", "50"))
TRANSACTIONAL_QUEUE_INTERVAL_SECONDS = int(os.getenv("TRANSACTIONAL_BATCH_INTERVAL_SECONDS", "300"))
TRANSACTIONAL_QUEUE_MAX_RECIPIENTS = int(os.getenv("TRANSACTIONAL_QUEUE_MAX_RECIPIENTS", "10000"))
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
LOGIN_ATTEMPTS: dict[str, list[float]] = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()


app = FastAPI(
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
tenant_store = TenantStore()
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def dashboard_session_auth(request: Request, call_next):
    if not IS_PRODUCTION:
        return await call_next(request)

    public_path = (
        request.url.path in {"/login", "/auth/login", "/health", "/favicon.ico"}
        or request.url.path.startswith("/static/")
    )
    if public_path:
        return await call_next(request)

    # API integrations retain workspace-key authentication without a browser cookie.
    if request.headers.get("X-API-Key"):
        return await call_next(request)

    dashboard_user = os.getenv("DASHBOARD_USER", "admin")
    session_secret = os.getenv("DASHBOARD_SESSION_SECRET", "")
    session_token = request.cookies.get("smartmailer_session", "")
    if session_secret and verify_session(session_token, dashboard_user, session_secret):
        return await call_next(request)

    if request.url.path.startswith("/v1/") or request.url.path in {
        "/verify", "/upload-csv", "/send-email", "/send-campaign"
    }:
        return JSONResponse(status_code=401, content={"detail": "Dashboard login is required."})
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Avoid opaque 422 responses and never echo submitted credentials."""
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part != "body") or "request",
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"message": "Invalid request. Check the listed fields.", "errors": errors},
    )


def custom_openapi():
    """Keep Swagger aligned with the custom 400 validation response."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title="SmartMailer AI", version="0.1.0", routes=app.routes)
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)
    schemas = schema.get("components", {}).get("schemas", {})
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


PROVIDER_REQUIRED_FIELDS = {
    "smtp": {"host", "port", "username", "password", "sender_name", "sender_email"},
    "office365": {"username", "password", "sender_name", "sender_email"},
    "graph": {"tenant_id", "client_id", "client_secret", "sender_email"},
    "sendgrid": {"api_key", "sender_name", "sender_email"},
}


def get_current_tenant(x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key is required.")
    tenant = tenant_store.tenant_for_api_key(x_api_key)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key.")
    return tenant


def validate_provider_credentials(provider: str, credentials: dict[str, Any]) -> str:
    provider = provider.strip().lower()
    required_fields = PROVIDER_REQUIRED_FIELDS.get(provider)
    if not required_fields:
        raise HTTPException(
            status_code=422,
            detail="Unsupported provider. Use smtp, office365, graph, or sendgrid.",
        )
    missing = sorted(field for field in required_fields if credentials.get(field) in (None, ""))
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Missing provider credentials: " + ", ".join(missing),
        )
    return provider


def append_workspace_signature(draft: dict, signature_html: str | None) -> dict:
    """Append a saved signature to generated copy only; manual emails stay unchanged."""
    if not signature_html:
        return draft
    result = dict(draft)
    result["html_body"] = f"{draft['html_body']}\n{signature_html}"
    result["text_body"] = f"{draft['text_body']}\n\n{html_to_text(signature_html)}".strip()
    return result



@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


class DashboardLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1_000)


@app.get("/login", include_in_schema=False)
def dashboard_login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.post("/auth/login", include_in_schema=False)
def dashboard_login(request: DashboardLoginRequest, http_request: Request):
    client_address = http_request.client.host if http_request.client else "unknown"
    cutoff = time.time() - 900
    with LOGIN_ATTEMPTS_LOCK:
        recent_attempts = [attempt for attempt in LOGIN_ATTEMPTS.get(client_address, []) if attempt > cutoff]
        LOGIN_ATTEMPTS[client_address] = recent_attempts
        if len(recent_attempts) >= 5:
            raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again later.")
    dashboard_user = os.getenv("DASHBOARD_USER", "admin")
    password_hash = os.getenv("DASHBOARD_APP_PASSWORD_HASH", "")
    session_secret = os.getenv("DASHBOARD_SESSION_SECRET", "")
    credentials_valid = (
        bool(password_hash and session_secret)
        and hmac.compare_digest(request.username, dashboard_user)
        and verify_password(request.password, password_hash)
    )
    if not credentials_valid:
        with LOGIN_ATTEMPTS_LOCK:
            LOGIN_ATTEMPTS.setdefault(client_address, []).append(time.time())
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    with LOGIN_ATTEMPTS_LOCK:
        LOGIN_ATTEMPTS.pop(client_address, None)
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie(
        "smartmailer_session",
        create_session(dashboard_user, session_secret),
        # Authentication has no application-enforced timeout. Browsers may still
        # enforce their own maximum cookie lifetime.
        max_age=315_360_000,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/auth/logout", include_in_schema=False)
def dashboard_logout():
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie("smartmailer_session", path="/", secure=IS_PRODUCTION, samesite="strict")
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "SmartMailer AI"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        os.path.join(STATIC_DIR, "favicon.svg"),
        media_type="image/svg+xml",
    )



# ==========================
# EMAIL VERIFICATION
# ==========================


@app.post("/verify")
def verify_emails(emails: list[str]):

    result = verify_email_list(emails)

    return {

        "results": result

    }



# ==========================
# CSV UPLOAD + CLEAN
# ==========================


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):


    file_location = f"temp_{file.filename}"


    with open(file_location, "wb") as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )



    emails = CSVReader.read_emails(
        file_location
    )



    verified_emails = verify_email_list(
        emails
    )



    clean_emails = CSVCleaner.clean_email_list(
        verified_emails
    )



    cleaned_file = CSVCleaner.save_clean_csv(
        clean_emails
    )



    os.remove(
        file_location
    )



    return {

        "uploaded_emails": len(emails),

        "verified_emails": len(verified_emails),

        "clean_emails": len(clean_emails),

        "file_created": cleaned_file

    }



# ==========================
# SINGLE EMAIL SENDING
# ==========================


class EmailRequest(BaseModel):

    to_email: str

    subject: str

    html_body: str | None = None

    text_body: str | None = None

    template_name: str | None = None

    variables: dict[str, str | int | float | bool] = Field(default_factory=dict)

    signature_name: str | None = None

    signature_html: str | None = None

    attachments: list[dict[str, str]] = Field(default_factory=list)


class TenantEmailRequest(EmailRequest):
    connection_name: str = Field(min_length=1, max_length=80)


class TransactionalBatchRecipient(BaseModel):
    to_email: str
    variables: dict[str, str | int | float | bool] = Field(default_factory=dict)


class TenantEmailBatchRequest(BaseModel):
    connection_name: str = Field(min_length=1, max_length=80)
    recipients: list[TransactionalBatchRecipient] = Field(min_length=1, max_length=25)
    subject: str = Field(min_length=1, max_length=200)
    html_body: str | None = None
    text_body: str | None = None
    template_name: str | None = None
    variables: dict[str, str | int | float | bool] = Field(default_factory=dict)
    signature_name: str | None = None
    signature_html: str | None = None
    attachments: list[dict[str, str]] = Field(default_factory=list)


class TransactionalQueueRequest(TenantEmailBatchRequest):
    recipients: list[TransactionalBatchRecipient] = Field(min_length=1, max_length=100_000)
    confirm_transactional: Literal[True]

    @model_validator(mode="after")
    def enforce_workspace_queue_limit(self):
        if not 1 <= TRANSACTIONAL_QUEUE_MAX_RECIPIENTS <= 100_000:
            raise ValueError("Server queue-recipient limit must be between 1 and 100000.")
        if len(self.recipients) > TRANSACTIONAL_QUEUE_MAX_RECIPIENTS:
            raise ValueError(
                f"This sender is currently configured for at most {TRANSACTIONAL_QUEUE_MAX_RECIPIENTS} recipients per queued job."
            )
        return self




@app.post("/send-email")
def send_email(request: EmailRequest):

    try:
        html_body, text_body = build_message(
            html_body=request.html_body,
            text_body=request.text_body,
            template_name=request.template_name,
            variables=recipient_variables(request.to_email, request.variables),
            signature_name=request.signature_name,
            signature_html=request.signature_html,
        )
        attachments = decode_attachments(request.attachments)
    except TransactionalEmailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


    sender = EmailSender(

        provider_name=EMAIL_PROVIDER,

        config=EMAIL_CONFIG

    )



    result = sender.send(

        to_email=request.to_email,

        subject=request.subject,

        html_body=html_body,

        text_body=text_body,

        attachments=attachments

    )



    return result


@app.post("/v1/transactional/send")
def send_tenant_transactional_email(
    request: TenantEmailRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Authenticated transactional send using a workspace-owned provider connection."""
    verification = verify_email_list([request.to_email])[0]
    if not verification["valid"]:
        raise HTTPException(status_code=422, detail="Recipient email address has an invalid format.")

    try:
        html_body, text_body = build_message(
            html_body=request.html_body,
            text_body=request.text_body,
            template_name=request.template_name,
            variables=recipient_variables(request.to_email, request.variables),
            signature_name=request.signature_name,
            signature_html=request.signature_html,
        )
        attachments = decode_attachments(request.attachments)
        provider_name, credentials = tenant_store.get_provider_connection(
            tenant["id"], request.connection_name
        )
    except TransactionalEmailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TenantStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = EmailSender(provider_name=provider_name, config=credentials).send(
        to_email=request.to_email,
        subject=request.subject,
        html_body=html_body,
        text_body=text_body,
        attachments=attachments,
    )
    return {"tenant_id": tenant["id"], "connection": request.connection_name, **result}


@app.post("/v1/transactional/send-batch")
def send_tenant_transactional_batch(
    request: TenantEmailBatchRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Send one approved transactional message to at most 25 contract-authorized recipients."""
    try:
        attachments = decode_attachments(request.attachments)
        provider_name, credentials = tenant_store.get_provider_connection(
            tenant["id"], request.connection_name
        )
    except TransactionalEmailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TenantStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sender = EmailSender(provider_name=provider_name, config=credentials)
    results = []
    for recipient in request.recipients:
        verification = verify_email_list([recipient.to_email])[0]
        if not verification["valid"]:
            results.append({"email": recipient.to_email, "status": "skipped", "reason": "Invalid email or receiving domain."})
            continue
        try:
            variables = recipient_variables(
                recipient.to_email, {**request.variables, **recipient.variables}
            )
            html_body, text_body = build_message(
                html_body=request.html_body,
                text_body=request.text_body,
                template_name=request.template_name,
                variables=variables,
                signature_name=request.signature_name,
                signature_html=request.signature_html,
            )
            result = sender.send(
                to_email=recipient.to_email,
                subject=request.subject,
                html_body=html_body,
                text_body=text_body,
                attachments=attachments,
            )
            results.append({"email": recipient.to_email, "status": "accepted", "result": result})
        except Exception as exc:
            results.append({"email": recipient.to_email, "status": "failed", "error": str(exc)})
    accepted = sum(item["status"] == "accepted" for item in results)
    return {
        "tenant_id": tenant["id"],
        "connection": request.connection_name,
        "accepted": accepted,
        "skipped_or_failed": len(results) - accepted,
        "results": results,
        "notice": "Provider acceptance is not an inbox-delivery guarantee. Use only for recipients authorized by the same transaction or contract.",
    }


@app.post("/v1/transactional/queue", status_code=status.HTTP_202_ACCEPTED)
def queue_tenant_transactional_batch(
    request: TransactionalQueueRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Queue contract-authorized messages in durable batches of 50 every five minutes."""
    try:
        # Validate now, before accepting a job that can never render or send.
        decode_attachments(request.attachments)
        tenant_store.get_provider_connection(tenant["id"], request.connection_name)
        queue = TransactionalQueue()
        queue.ping()
    except TransactionalEmailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TenantStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RedisQueueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    job_id = f"txq_{secrets.token_urlsafe(12)}"
    now = utc_now()
    request_data = request.model_dump()
    recipients = request_data.pop("recipients")
    job = request_data
    job.update({
        "id": job_id,
        "tenant_id": tenant["id"],
        "status": "queued",
        "accepted": 0,
        "skipped": 0,
        "failed": 0,
        "recipient_count": len(recipients),
        "processed": 0,
        "created_at": now,
        "updated_at": now,
    })
    try:
        queue.save(job)
        queue.save_recipients(job_id, recipients)
        queue.schedule(job_id, time.time())
    except RedisQueueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "job_id": job_id,
        "status": "queued",
        "recipients": len(recipients),
        "batch_size": TRANSACTIONAL_QUEUE_BATCH_SIZE,
        "interval_seconds": TRANSACTIONAL_QUEUE_INTERVAL_SECONDS,
        "notice": "The first batch runs when transactional_worker.py is running. Each following batch waits for the configured interval. Use only for recipients authorized by the relevant contract or transaction.",
    }


@app.get("/v1/transactional/queue/{job_id}")
def get_queued_transactional_batch(job_id: str, tenant: dict = Depends(get_current_tenant)):
    """Show queue progress without returning recipient addresses or provider credentials."""
    try:
        job = TransactionalQueue().get(job_id)
    except RedisQueueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not job or job.get("tenant_id") != tenant["id"]:
        raise HTTPException(status_code=404, detail="Queued transactional job was not found.")
    return {
        "job_id": job["id"], "status": job["status"], "recipients": job["recipient_count"],
        "processed": job["processed"], "accepted": job["accepted"],
        "skipped": job["skipped"], "failed": job["failed"],
        "created_at": job["created_at"], "updated_at": job["updated_at"],
        "last_error": job.get("last_error"),
    }





# ==========================
# BULK CAMPAIGN SENDING
# ==========================


class CampaignRequest(BaseModel):

    contacts: list[dict] = Field(default_factory=list)

    subject: str

    html_template: str | None = None

    text_template: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_common_campaign_field_names(cls, value):
        """Keep the campaign API compatible with single-email style payloads."""
        if not isinstance(value, dict):
            return value

        data = value.copy()
        if "html_template" not in data:
            data["html_template"] = data.get("html_body") or data.get("body")
        if "text_template" not in data and "text_body" in data:
            data["text_template"] = data["text_body"]

        if "contacts" not in data:
            recipients = data.get("recipients", data.get("emails"))
            if recipients is None:
                recipients = data.get("to_email", data.get("email", []))
            if isinstance(recipients, str):
                recipients = [recipients]
            if isinstance(recipients, list):
                data["contacts"] = [
                    {"email": recipient} if isinstance(recipient, str) else recipient
                    for recipient in recipients
                ]
        return data

    @model_validator(mode="after")
    def validate_campaign(self):
        if not self.contacts:
            raise ValueError("Provide at least one contact using contacts, emails, or recipients.")
        if not self.html_template:
            raise ValueError("Provide html_template (or html_body for compatibility).")

        invalid_contacts = [
            str(index) for index, contact in enumerate(self.contacts)
            if not isinstance(contact, dict) or not contact.get("email")
        ]
        if invalid_contacts:
            raise ValueError(
                "Each contact must include an email. Invalid contact indexes: "
                + ", ".join(invalid_contacts)
            )
        return self





@app.post("/send-campaign")
async def send_campaign(request: Request):

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON. Set Content-Type to application/json.",
        ) from exc

    try:
        campaign_request = CampaignRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid campaign request.",
                "errors": [
                    {
                        "field": ".".join(str(part) for part in error["loc"])
                        or "request",
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ],
            },
        ) from exc


    campaign = BulkSender()



    result = campaign.send_campaign(

        contacts=campaign_request.contacts,

        subject=campaign_request.subject,

        html_template=campaign_request.html_template,

        text_template=campaign_request.text_template

    )



    return {


        "provider": EMAIL_PROVIDER,

        "total": len(result),

        "results": result

    }


# ==========================
# MULTI-TENANT WORKSPACES
# ==========================


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    api_key_label: str = Field(default="default", max_length=120)


class APIKeyRotateRequest(BaseModel):
    label: str = Field(default="rotated", max_length=60)


class APIKeyCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=60)


class ProviderConnectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str
    credentials: dict[str, Any]


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    connection_name: str = Field(min_length=1, max_length=80)
    campaign_type: Literal["transactional", "marketing"] = "marketing"
    subject: str = Field(min_length=1, max_length=200)
    html_template: str = Field(min_length=1)
    text_template: str | None = None
    contacts: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class CampaignPreviewRequest(BaseModel):
    contact_index: int = Field(default=0, ge=0)


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    connection_name: str | None = Field(default=None, min_length=1, max_length=80)
    campaign_type: Literal["transactional", "marketing"] | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    html_template: str | None = Field(default=None, min_length=1)
    text_template: str | None = None
    contacts: list[dict[str, Any]] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one campaign field to update.")
        return self


class CampaignSendRequest(BaseModel):
    confirm_send: Literal[True]


class AICampaignDraftRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    connection_name: str = Field(min_length=1, max_length=80)
    campaign_type: Literal["transactional", "marketing"] = "marketing"
    purpose: str = Field(min_length=3, max_length=1_000)
    audience: str = Field(min_length=3, max_length=1_000)
    brand_voice: str = Field(default="clear, professional, and helpful", max_length=500)
    call_to_action: str = Field(min_length=2, max_length=500)
    variables: list[str] = Field(default_factory=list, max_length=30)
    contacts: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ContactSaveRequest(BaseModel):
    contacts: list[dict[str, Any]] = Field(min_length=1, max_length=1_000)


class WorkspaceSignatureRequest(BaseModel):
    signature_html: str | None = Field(default=None, max_length=20_000)


@app.post("/v1/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(request: TenantCreateRequest):
    """Creates a workspace and returns its API key exactly once."""
    try:
        tenant, api_key = tenant_store.create_tenant(request.name, request.api_key_label)
    except TenantStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tenant": tenant, "api_key": api_key, "warning": "Store this API key securely; it is shown once."}


@app.post("/v1/api-keys/rotate")
def rotate_tenant_api_key(
    request: APIKeyRotateRequest,
    x_api_key: str = Header(...),
    tenant: dict = Depends(get_current_tenant),
):
    """Revokes the caller's API key and returns a replacement once."""
    try:
        api_key = tenant_store.rotate_api_key(tenant["id"], x_api_key, request.label)
    except TenantStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"api_key": api_key, "warning": "The previous API key is revoked. Store this replacement securely; it is shown once."}


@app.post("/v1/api-keys", status_code=status.HTTP_201_CREATED)
def create_workspace_api_key(
    request: APIKeyCreateRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Create a separate sender key for another approved device or integration."""
    try:
        key, api_key = tenant_store.create_api_key(tenant["id"], request.label)
    except TenantStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "key": key,
        "api_key": api_key,
        "warning": "Store this API key securely; it is shown once and cannot be recovered.",
    }


@app.get("/v1/api-keys")
def list_workspace_api_keys(tenant: dict = Depends(get_current_tenant)):
    """List device-key records without exposing the token values."""
    return {"api_keys": tenant_store.list_api_keys(tenant["id"])}


@app.delete("/v1/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_workspace_api_key(key_id: str, tenant: dict = Depends(get_current_tenant)):
    """Revoke one lost device key while keeping other workspace keys working."""
    try:
        tenant_store.revoke_api_key(tenant["id"], key_id)
    except TenantStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/workspace")
def get_workspace(tenant: dict = Depends(get_current_tenant)):
    return {
        "tenant": tenant,
        "provider_connections": tenant_store.list_provider_connections(tenant["id"]),
        "ai_signature_configured": bool(tenant_store.get_workspace_signature(tenant["id"])),
    }


@app.put("/v1/workspace/signature")
def save_workspace_signature(
    request: WorkspaceSignatureRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Save the signature appended to all future AI-generated email drafts."""
    return tenant_store.save_workspace_signature(tenant["id"], request.signature_html)


@app.put("/v1/provider-connections")
def save_provider_connection(
    request: ProviderConnectionRequest,
    tenant: dict = Depends(get_current_tenant),
):
    provider = validate_provider_credentials(request.provider, request.credentials)
    try:
        connection = tenant_store.save_provider_connection(
            tenant["id"], request.name, provider, request.credentials
        )
    except TenantStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "saved", "connection": connection}


# ==========================
# WORKSPACE CAMPAIGNS
# ==========================


@app.post("/v1/contacts", status_code=status.HTTP_201_CREATED)
def save_contacts(
    request: ContactSaveRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Save or update workspace contacts. Sending is never triggered here."""
    try:
        contacts = normalize_contacts(request.contacts)
        saved = tenant_store.save_contacts(tenant["id"], contacts)
    except (TenantStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"saved": len(saved), "contacts": saved}


@app.get("/v1/contacts")
def list_contacts(tenant: dict = Depends(get_current_tenant)):
    return {"contacts": tenant_store.list_contacts(tenant["id"])}


@app.post("/v1/contacts/import-csv", status_code=status.HTTP_201_CREATED)
async def import_contacts_csv(
    file: UploadFile = File(...),
    tenant: dict = Depends(get_current_tenant),
):
    """Validate and save contact CSV data to the current workspace without creating files."""
    try:
        raw_contacts, total_rows = parse_contacts_csv(await file.read())
    except ContactCSVError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid_contacts = []
    invalid_rows = []
    for row_number, contact in enumerate(raw_contacts, start=2):
        try:
            valid_contacts.extend(normalize_contacts([contact]))
        except ValueError as exc:
            invalid_rows.append({"row": row_number, "reason": str(exc)})
    try:
        valid_contacts = normalize_contacts(valid_contacts) if valid_contacts else []
        if not valid_contacts:
            raise ValueError("No valid contacts were found in the CSV.")
        saved = tenant_store.save_contacts(tenant["id"], valid_contacts)
    except (TenantStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "rows_read": total_rows,
        "saved": len(saved),
        "invalid_rows": invalid_rows,
        "notice": "Contacts were saved to this workspace. No email was sent.",
    }


@app.delete("/v1/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: str, tenant: dict = Depends(get_current_tenant)):
    try:
        tenant_store.delete_contact(tenant["id"], contact_id)
    except TenantStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/campaigns", status_code=status.HTTP_201_CREATED)
def create_campaign(
    request: CampaignCreateRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Create a workspace-scoped campaign draft. No email is sent."""
    try:
        campaign = tenant_store.create_campaign(
            tenant["id"],
            {**request.model_dump(), "contacts": normalize_contacts(request.contacts)},
        )
    except (TenantStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"campaign": campaign, "notice": "Draft saved. Preview it before confirming a send."}


@app.post("/v1/campaigns/ai-draft", status_code=status.HTTP_201_CREATED)
def create_ai_campaign_draft(
    request: AICampaignDraftRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Generate an AI email and save it as a reviewable campaign draft; never sends."""
    try:
        contacts = normalize_contacts(request.contacts)
        ai_draft = generate_email_draft(
            tenant["id"],
            {
                "email_type": request.campaign_type,
                "purpose": request.purpose,
                "audience": request.audience,
                "brand_voice": request.brand_voice,
                "call_to_action": request.call_to_action,
                "variables": request.variables,
            },
        )
        ai_draft = append_workspace_signature(
            ai_draft, tenant_store.get_workspace_signature(tenant["id"])
        )
        campaign = tenant_store.create_campaign(
            tenant["id"],
            {
                "name": request.name,
                "connection_name": request.connection_name,
                "campaign_type": request.campaign_type,
                "subject": ai_draft["subject"],
                "html_template": ai_draft["html_body"],
                "text_template": ai_draft["text_body"],
                "contacts": contacts,
            },
        )
    except AIContentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (TenantStoreError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    preflight = analyze_email(
        ai_draft["subject"], ai_draft["html_body"], request.campaign_type
    )
    return {
        "campaign": campaign,
        "ai_draft": ai_draft,
        "deliverability": preflight,
        "notice": "AI created a draft only. Preview and review it before confirming a send.",
    }


@app.put("/v1/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: str,
    request: CampaignUpdateRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Edit an unsent draft; no email is sent."""
    try:
        changes = request.model_dump(exclude_unset=True)
        if "contacts" in changes:
            changes["contacts"] = normalize_contacts(changes["contacts"])
        campaign = tenant_store.update_campaign(tenant["id"], campaign_id, changes)
    except TenantStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"campaign": campaign, "notice": "Draft updated. Preview it again before sending."}


@app.get("/v1/campaigns")
def list_campaigns(tenant: dict = Depends(get_current_tenant)):
    return {"campaigns": tenant_store.list_campaigns(tenant["id"])}


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, tenant: dict = Depends(get_current_tenant)):
    try:
        return {"campaign": tenant_store.get_campaign(tenant["id"], campaign_id)}
    except TenantStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/v1/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: str, tenant: dict = Depends(get_current_tenant)):
    try:
        tenant_store.delete_campaign(tenant["id"], campaign_id)
    except TenantStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/campaigns/{campaign_id}/preview")
def preview_campaign(
    campaign_id: str,
    request: CampaignPreviewRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Render one contact and return a deliverability preflight. No email is sent."""
    try:
        campaign = tenant_store.get_campaign(tenant["id"], campaign_id)
        contact = campaign["contacts"][request.contact_index]
        message = render_campaign(campaign, contact)
    except TenantStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=400, detail="contact_index is outside this campaign's contact list.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "campaign_id": campaign_id,
        "contact": {"email": contact["email"]},
        "message": message,
        "deliverability": analyze_email(message["subject"], message["html_body"], campaign["campaign_type"]),
        "notice": "Preview only. No email has been sent.",
    }


@app.post("/v1/campaigns/{campaign_id}/send")
def send_campaign_draft(
    campaign_id: str,
    request: CampaignSendRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Send a saved campaign only after an explicit confirmation field is supplied."""
    try:
        campaign = tenant_store.get_campaign(tenant["id"], campaign_id)
        provider_name, credentials = tenant_store.get_provider_connection(
            tenant["id"], campaign["connection_name"]
        )
    except TenantStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    sender = EmailSender(provider_name=provider_name, config=credentials)
    results = []
    for contact in campaign["contacts"]:
        try:
            message = render_campaign(campaign, contact)
            result = sender.send(**message)
            results.append({"email": contact["email"], "status": "accepted", "result": result})
        except Exception as exc:
            results.append({"email": contact["email"], "status": "failed", "error": str(exc)})

    failures = sum(item["status"] == "failed" for item in results)
    campaign_status = "sent" if failures == 0 else "partially_sent"
    tenant_store.set_campaign_status(tenant["id"], campaign_id, campaign_status)
    return {
        "campaign_id": campaign_id,
        "status": campaign_status,
        "accepted": len(results) - failures,
        "failed": failures,
        "results": results,
        "notice": "Provider acceptance is not an inbox-delivery guarantee. Check provider events for delivery status.",
    }


# ==========================
# AI + DELIVERABILITY
# ==========================


class DeliverabilityRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    html_body: str = Field(min_length=1)
    email_type: str


class AIDraftRequest(BaseModel):
    email_type: str
    purpose: str = Field(min_length=3, max_length=1_000)
    audience: str = Field(min_length=3, max_length=1_000)
    brand_voice: str = Field(default="clear, professional, and helpful", max_length=500)
    call_to_action: str = Field(min_length=2, max_length=500)
    variables: list[str] = Field(default_factory=list, max_length=30)


class AISignatureRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    sender_name: str | None = Field(default=None, max_length=120)
    team_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    brand_color: str = Field(default="#1f4e79", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str = Field(default="#666666", pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_url: str | None = Field(default=None, max_length=2_000)
    style: Literal["auto", "minimal", "modern", "formal", "friendly"] = "auto"
    variation_count: int = Field(default=3, ge=1, le=3)


@app.post("/v1/deliverability/analyze")
def analyze_deliverability(
    request: DeliverabilityRequest,
    tenant: dict = Depends(get_current_tenant),
):
    try:
        report = analyze_email(request.subject, request.html_body, request.email_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tenant_id": tenant["id"], **report}


@app.post("/v1/ai/generate-email")
def generate_ai_email(
    request: AIDraftRequest,
    tenant: dict = Depends(get_current_tenant),
):
    if request.email_type not in {"transactional", "marketing"}:
        raise HTTPException(status_code=422, detail="email_type must be transactional or marketing.")
    try:
        draft = generate_email_draft(tenant["id"], request.model_dump())
    except AIContentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    draft = append_workspace_signature(draft, tenant_store.get_workspace_signature(tenant["id"]))
    deliverability = analyze_email(draft["subject"], draft["html_body"], request.email_type)
    return {
        "tenant_id": tenant["id"],
        "draft": draft,
        "deliverability": deliverability,
        "notice": "Review the generated draft and the deliverability report before sending.",
    }


@app.post("/v1/ai/generate-signature")
def generate_ai_signature(
    request: AISignatureRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Generate optional signature HTML; it is never automatically attached or sent."""
    if request.logo_url and not request.logo_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="logo_url must use HTTPS.")
    try:
        signature = generate_signature_draft(tenant["id"], request.model_dump())
    except AIContentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        **signature,
        "notice": "Choose one signature_html and copy it into an email request only after review. No email has been sent.",
    }
