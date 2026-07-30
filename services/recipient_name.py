"""Privacy-preserving, best-effort recipient-name inference.

This module never looks up a mailbox or external data source. It only derives a
display name from the local part of an address when that part looks like a name.
"""

from __future__ import annotations

import re
from typing import Any


ROLE_ADDRESSES = {
    "admin", "billing", "careers", "contact", "finance", "hello", "help",
    "info", "invoices", "mail", "marketing", "noreply", "no-reply", "sales",
    "security", "support", "team", "webmaster",
}


def infer_first_name(email: str) -> str | None:
    """Return a plausible first name from an address, or None when it is unsafe to guess."""
    local_part = email.strip().lower().split("@", 1)[0].split("+", 1)[0]
    if not local_part or local_part in ROLE_ADDRESSES:
        return None
    parts = [part for part in re.split(r"[._-]+", local_part) if part]
    if not parts or not parts[0].isalpha() or len(parts[0]) < 2:
        return None
    return parts[0].capitalize()


def recipient_variables(email: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Preserve supplied values and provide a safe greeting fallback for templates."""
    result = dict(variables)
    if result.get("first_name"):
        return result
    if result.get("name"):
        result["first_name"] = str(result["name"]).strip().split(maxsplit=1)[0]
    else:
        result["first_name"] = infer_first_name(email) or "there"
    return result
