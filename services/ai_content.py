"""OpenAI-backed email drafting. The API key remains server-side."""

from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIContentError(RuntimeError):
    pass


DOUBLE_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
SINGLE_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _normalize_draft_placeholders(draft: dict, allowed_variables: list[str]) -> dict:
    """Use project-standard braces and reject invented AI template variables."""
    normalized = dict(draft)
    for field in ("html_body", "text_body"):
        normalized[field] = DOUBLE_PLACEHOLDER.sub(r"{\1}", str(normalized[field]))

    allowed = set(allowed_variables)
    used = {
        match.group(1)
        for field in ("html_body", "text_body")
        for match in SINGLE_PLACEHOLDER.finditer(normalized[field])
    }
    unknown = sorted(used - allowed)
    if unknown:
        raise AIContentError(
            "AI provider invented unsupported template variables: " + ", ".join(unknown)
        )

    subject_text = " ".join(
        [str(normalized.get("subject", "")), *map(str, normalized.get("subject_variants", []))]
    )
    if SINGLE_PLACEHOLDER.search(DOUBLE_PLACEHOLDER.sub(r"{\1}", subject_text)):
        raise AIContentError("AI provider put a template variable in a subject line. Please retry.")
    return normalized


def _response_text(response: dict) -> str:
    if response.get("output_text"):
        return response["output_text"]
    parts = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                parts.append(content.get("text", ""))
    return "".join(parts)


def generate_email_draft(tenant_id: str, request_data: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIContentError("OPENAI_API_KEY is not configured for AI drafting.")

    email_type = request_data["email_type"]
    system_prompt = (
        "You write compliant, deliverability-conscious business email. "
        "Do not claim guaranteed inbox placement. Do not use deceptive urgency, misleading claims, "
        "or spammy language. Marketing drafts must include an unsubscribe placeholder. "
        "Use only variable names present in the supplied variables array. Write every variable with "
        "exactly one opening and one closing brace, for example {first_name}; never use double braces, "
        "rename, capitalize, or invent a variable. Do not put variables in subject lines. Preserve any "
        "literal HTTPS call-to-action URL exactly as supplied. "
        "Return only valid JSON with: subject, subject_variants (array of 3 strings), html_body, text_body."
    )
    user_prompt = json.dumps(request_data, ensure_ascii=False)
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        "input": [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": f"Create a {email_type} email from this brief: {user_prompt}"},
        ],
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "medium"},
        "store": False,
        "safety_identifier": hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(),
    }
    http_request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIContentError(f"AI provider rejected the request: {detail}") from exc
    except URLError as exc:
        raise AIContentError("Unable to reach the AI provider.") from exc

    try:
        draft = json.loads(_response_text(payload))
    except json.JSONDecodeError as exc:
        raise AIContentError("AI provider returned a draft in an invalid format. Please retry.") from exc
    required = {"subject", "subject_variants", "html_body", "text_body"}
    if not required.issubset(draft) or not isinstance(draft["subject_variants"], list):
        raise AIContentError("AI provider returned an incomplete draft. Please retry.")
    return _normalize_draft_placeholders(
        {key: draft[key] for key in required}, request_data.get("variables", [])
    )


def generate_signature_draft(tenant_id: str, request_data: dict) -> dict:
    """Generate a compact HTML email signature without sending or storing it."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIContentError("OPENAI_API_KEY is not configured for AI drafting.")

    system_prompt = (
        "You create compact, professional HTML email signatures. Return only valid JSON with "
        "one key: signatures, an array of objects with label and signature_html. Create exactly "
        "variation_count visually distinct options. Use inline CSS only. Do not include scripts, "
        "forms, tracking pixels, base64 data, or markdown. Only include an image when logo_url is "
        "supplied, and use it exactly as supplied."
    )
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        "input": [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": json.dumps(request_data, ensure_ascii=False)},
        ],
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low"},
        "store": False,
        "safety_identifier": hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(),
    }
    http_request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=45) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIContentError(f"AI provider rejected the request: {detail}") from exc
    except URLError as exc:
        raise AIContentError("Unable to reach the AI provider.") from exc

    try:
        signature = json.loads(_response_text(response_payload))
    except json.JSONDecodeError as exc:
        raise AIContentError("AI provider returned a signature in an invalid format. Please retry.") from exc
    signatures = signature.get("signatures") if isinstance(signature, dict) else None
    if not isinstance(signatures, list) or not signatures:
        raise AIContentError("AI provider returned an incomplete signature. Please retry.")
    normalized = []
    for item in signatures:
        if not isinstance(item, dict) or not isinstance(item.get("signature_html"), str):
            raise AIContentError("AI provider returned an incomplete signature. Please retry.")
        normalized.append({
            "label": str(item.get("label") or "Signature option"),
            "signature_html": item["signature_html"].strip(),
        })
    return {"signatures": normalized}
