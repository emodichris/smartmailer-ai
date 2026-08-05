# SmartMailer AI

SmartMailer AI provides transactional and bulk email sending. The `/v1` endpoints
are workspace-scoped: each business creates a workspace, receives an API key, and
stores its own encrypted provider connection.

## Local setup

1. Copy `.env.example` to `.env` and preserve any legacy provider settings already
   in use.
2. Generate a credential-encryption key:

   ```powershell
   .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Add the output to `.env` as `CREDENTIAL_ENCRYPTION_KEY`.
4. Start the API:

   ```powershell
   .\.venv\Scripts\uvicorn.exe app:app --reload
   ```

Open `http://127.0.0.1:8000/docs` to enter and submit requests interactively.

## Workspace workflow

1. `POST /v1/tenants` creates a business workspace and returns an API key once. The
   `api_key_label` is only a label such as `production`; never paste a provider secret there.
2. Use that value in the `X-API-Key` header.
3. `PUT /v1/provider-connections` saves the business's SMTP, Office365, Graph, or
   SendGrid details. Credentials are encrypted in the local tenant database.
4. `POST /v1/transactional/send` sends through a named, workspace-owned connection.
5. `POST /v1/api-keys` creates a separate workspace token for another approved
   computer or integration. Label it clearly, for example `office-laptop`.
6. `GET /v1/api-keys` displays only safe token records, never token values.
7. `DELETE /v1/api-keys/{key_id}` revokes one lost device token without affecting
   other devices. Create a replacement before revoking the last active token.
8. `POST /v1/api-keys/rotate` immediately revokes the caller's workspace API key and
   returns a replacement. Use it if that particular key is exposed.

Example provider connection:

```json
{
  "name": "primary-sendgrid",
  "provider": "sendgrid",
  "credentials": {
    "api_key": "provider-api-key",
    "sender_name": "Example Business",
    "sender_email": "billing@example.com"
  }
}
```

Example transactional request:

```json
{
  "connection_name": "primary-sendgrid",
  "to_email": "customer@example.com",
  "subject": "Your invoice",
  "template_name": "invoice",
  "variables": {
    "first_name": "Ada",
    "invoice_number": "INV-1001",
    "invoice_url": "https://example.com/invoices/INV-1001"
  }
}
```

For one contract-related notification to several authorized organizations, use
`POST /v1/transactional/send-batch`. It accepts up to 25 recipients per request,
uses the same subject and invoice link, and can personalize each recipient with
its own variables. It is not for cold leads or marketing lists.

### Recipient greetings

For reliable personalization, include `first_name` in request variables or in
each campaign contact. If it is absent, SmartMailer makes a local best-effort
guess from the text before `@` in the recipient address (for example,
`john.smith@example.com` becomes `John`). It never accesses recipient mailboxes
or external identity data, and uses `there` when an address looks role-based
such as `billing@example.com`.

### Optional signatures

SmartMailer no longer appends a signature automatically. Add your own optional
signature per transactional request using `signature_html`, for example:

```json
{
  "signature_html": "<p>Kind regards,<br><strong>Valencia Group</strong><br>support@example.com</p>"
}
```

Alternatively, set `signature_name` to `default` to use the bundled signature.
Do not send both fields in the same request.

When OpenAI API credits are available, `POST /v1/ai/generate-signature` can
generate `signature_html` from a company name, colors, team details, and an
optional HTTPS logo URL. By default it returns three different style options;
set `style` to `minimal`, `modern`, `formal`, or `friendly` to guide them. It
only returns HTML; it never attaches or sends it automatically.

To append a chosen signature to every future AI-generated email draft, save it
with `PUT /v1/workspace/signature` using `{ "signature_html": "..." }` and the
workspace API key. This affects AI-generated drafts only; manual transactional
email requests remain signature-free unless they include `signature_html`.

## Campaign workflow

The workspace campaign API is deliberately draft-first: creating and previewing a
campaign never sends email. Campaigns are limited to 100 normalized, unique
contacts per draft while this local synchronous sender is in use.

1. `POST /v1/contacts` saves normalized contacts in the workspace; `GET /v1/contacts`
   lists them, and `DELETE /v1/contacts/{contact_id}` removes one.
   `POST /v1/contacts/import-csv` imports a UTF-8 CSV (up to 5 MB) with an
   `email` column and optional columns such as `first_name`; it saves valid,
   deduplicated contacts and reports invalid rows without sending any email.
2. `POST /v1/campaigns` creates a draft using a saved provider connection.
3. `POST /v1/campaigns/ai-draft` uses the configured OpenAI key to generate the
   email copy and saves it as a draft; it never sends email.
4. `POST /v1/campaigns/{campaign_id}/preview` renders one contact and returns a
   deliverability preflight without sending.
5. `POST /v1/campaigns/{campaign_id}/send` sends only when the request body is
   exactly `{ "confirm_send": true }`.
6. `GET /v1/campaigns` lists the workspace's drafts and send status.
7. `PUT /v1/campaigns/{campaign_id}` edits an unsent draft and
   `DELETE /v1/campaigns/{campaign_id}` removes one.

Every campaign endpoint requires the workspace `X-API-Key` header.

Example draft request:

```json
{
  "name": "July invoice reminder",
  "connection_name": "primary-sendgrid",
  "campaign_type": "transactional",
  "subject": "Your invoice is ready",
  "html_template": "<p>Hello {first_name},</p><p>Your invoice <strong>#{invoice_number}</strong> is ready.</p><p><a href=\"{invoice_url}\">View invoice</a></p>",
  "contacts": [
    {
      "email": "customer@example.com",
      "first_name": "Ada",
      "invoice_number": "INV-1001",
      "invoice_url": "https://example.com/invoices/INV-1001"
    }
  ]
}
```

To generate the copy automatically, use `POST /v1/campaigns/ai-draft` with the
same contact list plus a purpose, audience, brand voice, and call to action. Set
`OPENAI_API_KEY` in `.env` before using this endpoint. Review the generated
campaign preview before sending, especially its links and any unsubscribe text.

## AI and deliverability preflight

Set `OPENAI_API_KEY` in `.env` to enable `POST /v1/ai/generate-email`. It creates
transactional or marketing drafts, including subject variants, then automatically
returns a deliverability preflight report. `POST /v1/deliverability/analyze` is
available without an AI key and checks subject risk signals, links, risky phrases,
and marketing unsubscribe language.

Example AI draft request:

```json
{
  "email_type": "transactional",
  "purpose": "Notify a customer that their invoice is ready.",
  "audience": "A customer who has completed a purchase.",
  "brand_voice": "warm and professional",
  "call_to_action": "View your invoice",
  "variables": ["first_name", "invoice_number", "invoice_url"]
}
```

## Redis queue setup

The future high-volume transactional queue uses Redis so scheduled batches can
survive FastAPI restarts. Install Docker Desktop, then start Redis from this
project folder:

```powershell
docker compose up -d redis
```

Check that it is running with:

```powershell
docker compose ps
```

The scheduled transactional sender defaults to 50 recipients every five
minutes. Start it in a second PowerShell window after Redis is running:

```powershell
.\.venv\Scripts\python.exe transactional_worker.py
```

Use `POST /v1/transactional/queue` in `/docs` to add a job. It defaults to up to
10,000 recipients in one job. After confirming provider capacity, set
`TRANSACTIONAL_QUEUE_MAX_RECIPIENTS=100000` in `.env` and restart FastAPI to
allow up to 100,000 in one job. It sends the first batch when the worker is available,
then sends another batch after the configured interval. Change
`TRANSACTIONAL_BATCH_INTERVAL_SECONDS` in `.env` and restart the worker to
change that interval; the minimum is 60 seconds. The request must include
`"confirm_transactional": true`; it is only for recipients authorized by the
same transaction or contract. Check progress with
`GET /v1/transactional/queue/{job_id}`. Provider acceptance is not a guarantee
that a message reached the inbox.

The dashboard's **Transactional** view provides the same guarded workflow without
manual API calls. Upload a UTF-8 CSV with `email`, `first_name`, `invoice_number`,
and `invoice_url`, validate and preview one rendered recipient, confirm that every
recipient is authorized by the relevant transaction or contract, and then queue
the reviewed file. The dashboard reports queue progress without displaying the
remaining recipient list. A CSV may use `{Email}` inside `invoice_url`; the server
resolves it to that row's normalized email before queueing.

## Production note

The included SQLite store is appropriate for local development only. A public
multi-tenant deployment needs PostgreSQL, a managed encryption key, authentication
for workspace administration, background job processing, rate limits, webhook
verification, and a tracking domain before accepting customer traffic.

### Private Hostinger VPS deployment

`docker-compose.prod.yml` provides a small, single-server deployment for an
owner-operated or private beta installation. It runs the FastAPI dashboard, the
transactional worker, Redis, and Caddy with persistent Docker volumes. Caddy
adds HTTPS and a password gate in front of the entire dashboard.

On the VPS, clone the private repository, copy `.env.example` to `.env`, and
replace every placeholder with a production value. Set `APP_DOMAIN` to the
dedicated subdomain, such as `sender.example.com`. Generate the Caddy password
hash without putting the plaintext password in shell history:

```bash
docker run --rm -i caddy:2-alpine caddy hash-password
```

Paste the generated hash into `DASHBOARD_PASSWORD_HASH`. Then deploy:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Allow inbound TCP ports 80 and 443, restrict SSH port 22 to trusted addresses
where practical, and never expose Redis port 6379. Back up the
`smartmailer-data` and `redis-data` volumes outside the VPS. This single-server
layout is not a replacement for PostgreSQL and managed Redis when serving
unrelated customer organizations or scaling across multiple servers.
