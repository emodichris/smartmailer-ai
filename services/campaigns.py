"""Campaign drafting, safe previewing, and controlled delivery helpers."""

from __future__ import annotations

from typing import Any

from email_verifier.verifier import verify_email_list
from services.recipient_name import recipient_variables
from services.transactional_email import TransactionalEmailError, html_to_text, render_variables


def normalize_contacts(contacts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validate, normalize, and deduplicate contacts by email address."""
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, contact in enumerate(contacts):
        if not isinstance(contact, dict):
            raise ValueError(f"Contact {index + 1} must be an object with an email field.")
        raw_email = str(contact.get("email", "")).strip().lower()
        if not raw_email or not verify_email_list([raw_email])[0]["valid"]:
            raise ValueError(f"Contact {index + 1} has an invalid email address.")
        if raw_email in seen:
            continue
        seen.add(raw_email)
        normalized_contact = {str(key): str(value) for key, value in contact.items() if value is not None} | {"email": raw_email}
        normalized.append(recipient_variables(raw_email, normalized_contact))
    if not normalized:
        raise ValueError("Provide at least one valid contact.")
    return normalized


def render_campaign(campaign: dict[str, Any], contact: dict[str, str]) -> dict[str, str]:
    """Render one contact without supporting arbitrary template expressions."""
    try:
        variables = recipient_variables(contact["email"], contact)
        html_body = render_variables(campaign["html_template"], variables)
        text_template = campaign.get("text_template")
        text_body = render_variables(text_template, variables) if text_template else html_to_text(html_body)
    except TransactionalEmailError as exc:
        raise ValueError(str(exc)) from exc
    return {"to_email": contact["email"], "subject": campaign["subject"], "html_body": html_body, "text_body": text_body}
