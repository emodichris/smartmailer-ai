import re
import os
from functools import lru_cache

import requests


def check_email_format(email):
    """Apply conservative RFC-style syntax and DNS-label checks."""
    if not isinstance(email, str) or len(email) > 254 or email.count("@") != 1:
        return False
    local, domain = email.rsplit("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    if len(domain) > 253 or "." not in domain:
        return False
    return all(
        label and len(label) <= 63 and not label.startswith("-")
        and not label.endswith("-") and re.fullmatch(r"[A-Za-z0-9-]+", label)
        for label in domain.split(".")
    )


@lru_cache(maxsize=10_000)
def check_receiving_domain_status(domain: str) -> str:
    """Return valid, invalid, or unavailable for a domain's MX lookup."""
    try:
        response = requests.get(
            os.getenv("EMAIL_DOH_URL", "https://cloudflare-dns.com/dns-query"),
            params={"name": domain, "type": "MX"},
            headers={"Accept": "application/dns-json"}, timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return "unavailable"
    answers = [answer for answer in payload.get("Answer", []) if answer.get("type") == 15]
    if payload.get("Status") != 0 or not answers:
        return "invalid"
    if all(str(answer.get("data", "")).strip().endswith(" .") for answer in answers):
        return "invalid"
    return "valid"


@lru_cache(maxsize=10_000)
def check_receiving_domain(domain: str) -> bool:
    """Check that a domain publishes MX records through DNS-over-HTTPS.

    This validates the receiving domain only. It deliberately does not probe an
    individual inbox, because many mail servers block or conceal such checks.
    """
    return check_receiving_domain_status(domain) == "valid"


def verify_email_list(emails):
    results = []

    for email in emails:
        normalized_email = email.strip().lower()
        format_valid = check_email_format(normalized_email)
        domain_valid = (
            check_receiving_domain(normalized_email.rsplit("@", 1)[1])
            if format_valid
            else False
        )
        results.append({
            "email": normalized_email,
            "format_valid": format_valid,
            "domain_valid": domain_valid,
            "valid": format_valid and domain_valid,
        })

    return results
