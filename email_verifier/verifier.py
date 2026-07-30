import re
import os
from functools import lru_cache

import requests


def check_email_format(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"

    if re.match(pattern, email):
        return True

    return False


@lru_cache(maxsize=10_000)
def check_receiving_domain(domain: str) -> bool:
    """Check that a domain publishes MX records through DNS-over-HTTPS.

    This validates the receiving domain only. It deliberately does not probe an
    individual inbox, because many mail servers block or conceal such checks.
    """
    try:
        response = requests.get(
            os.getenv("EMAIL_DOH_URL", "https://cloudflare-dns.com/dns-query"),
            params={"name": domain, "type": "MX"},
            headers={"Accept": "application/dns-json"},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False
    return payload.get("Status") == 0 and any(
        answer.get("type") == 15 for answer in payload.get("Answer", [])
    )


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
