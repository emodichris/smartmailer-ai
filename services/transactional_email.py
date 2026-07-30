"""Rendering and attachment helpers for transactional messages."""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = PROJECT_ROOT / "templates" / "transactional"
SIGNATURE_ROOT = PROJECT_ROOT / "signatures"
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class TransactionalEmailError(ValueError):
    """Raised when a transactional request cannot be rendered safely."""


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def render_variables(content: str, variables: dict[str, Any]) -> str:
    """Replace {variable} tokens and reject requests with missing values."""
    missing = sorted({match.group(1) for match in PLACEHOLDER.finditer(content)
                      if match.group(1) not in variables})
    if missing:
        raise TransactionalEmailError(
            "Missing template variables: " + ", ".join(missing)
        )
    return PLACEHOLDER.sub(lambda match: str(variables[match.group(1)]), content)


def read_template(template_name: str, extension: str, required: bool = True) -> str | None:
    """Load a template by name without allowing paths outside its directory."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", template_name):
        raise TransactionalEmailError("Template names may contain letters, numbers, _ and - only.")
    path = TEMPLATE_ROOT / f"{template_name}.{extension}"
    if not path.is_file():
        if required:
            raise TransactionalEmailError(f"Transactional template '{template_name}.{extension}' was not found.")
        return None
    return path.read_text(encoding="utf-8")


def read_signature(signature_name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", signature_name):
        raise TransactionalEmailError("Signature names may contain letters, numbers, _ and - only.")
    path = SIGNATURE_ROOT / f"{signature_name}.html"
    if not path.is_file():
        raise TransactionalEmailError(f"Signature '{signature_name}.html' was not found.")
    return path.read_text(encoding="utf-8")


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def build_message(
    *,
    html_body: str | None,
    text_body: str | None,
    template_name: str | None,
    variables: dict[str, Any],
    signature_name: str | None,
    signature_html: str | None = None,
) -> tuple[str, str]:
    if template_name:
        if html_body is not None or text_body is not None:
            raise TransactionalEmailError("Use either template_name or html_body/text_body, not both.")
        html_body = read_template(template_name, "html")
        text_body = read_template(template_name, "txt", required=False)
    if not html_body:
        raise TransactionalEmailError("Provide html_body or a template_name.")

    html_body = render_variables(html_body, variables)
    text_body = render_variables(text_body, variables) if text_body else html_to_text(html_body)

    if signature_name and signature_html:
        raise TransactionalEmailError("Use either signature_name or signature_html, not both.")
    if signature_name:
        signature = render_variables(read_signature(signature_name), variables)
        html_body = f"{html_body}\n{signature}"
        text_body = f"{text_body}\n\n{html_to_text(signature)}".strip()
    elif signature_html:
        signature = render_variables(signature_html, variables)
        html_body = f"{html_body}\n{signature}"
        text_body = f"{text_body}\n\n{html_to_text(signature)}".strip()
    return html_body, text_body


def decode_attachments(attachments: list[dict[str, str]]) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    total_size = 0
    for attachment in attachments:
        filename = attachment.get("filename", "")
        encoded = attachment.get("content_base64", "")
        if not filename or Path(filename).name != filename:
            raise TransactionalEmailError("Each attachment needs a simple filename without a path.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise TransactionalEmailError(f"Attachment '{filename}' is not valid base64.") from None
        total_size += len(content)
        if total_size > MAX_ATTACHMENT_BYTES:
            raise TransactionalEmailError("Attachments may not exceed 10 MB in total.")
        decoded.append({
            "filename": filename,
            "content": content,
            "content_type": attachment.get("content_type")
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream",
        })
    return decoded
