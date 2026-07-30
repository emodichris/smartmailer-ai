"""Local preflight checks for marketing and transactional email content."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse


RISK_TERMS = {
    "act now": 8,
    "buy now": 6,
    "cash": 5,
    "click here": 4,
    "congratulations": 5,
    "free": 5,
    "guarantee": 5,
    "limited time": 4,
    "make money": 8,
    "urgent": 5,
    "winner": 8,
}


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def analyze_email(subject: str, html_body: str, email_type: str) -> dict:
    """Returns explainable, heuristic risk signals; it is not an inbox guarantee."""
    normalized_type = email_type.strip().lower()
    if normalized_type not in {"transactional", "marketing"}:
        raise ValueError("email_type must be transactional or marketing.")

    body_text = re.sub(r"<[^>]+>", " ", html_body)
    searchable = f"{subject} {body_text}".lower()
    score = 0
    issues: list[dict] = []
    recommendations: list[str] = []

    for term, weight in RISK_TERMS.items():
        if term in searchable:
            score += weight
            issues.append({"type": "risk_phrase", "value": term, "weight": weight})

    if len(subject) < 12:
        score += 4
        issues.append({"type": "subject_length", "value": "Subject is very short.", "weight": 4})
    elif len(subject) > 60:
        score += 5
        issues.append({"type": "subject_length", "value": "Subject exceeds 60 characters.", "weight": 5})
        recommendations.append("Keep the subject line under roughly 60 characters where possible.")

    uppercase_letters = [character for character in subject if character.isalpha()]
    if uppercase_letters and sum(character.isupper() for character in uppercase_letters) / len(uppercase_letters) > 0.55:
        score += 8
        issues.append({"type": "subject_caps", "value": "Subject contains excessive capitals.", "weight": 8})
        recommendations.append("Use sentence case instead of all-capital subject lines.")
    if subject.count("!") > 1:
        score += 5
        issues.append({"type": "subject_punctuation", "value": "Subject has multiple exclamation marks.", "weight": 5})

    parser = _LinkCollector()
    parser.feed(html_body)
    external_links = [link for link in parser.links if urlparse(link).scheme in {"http", "https"}]
    if len(external_links) > 8:
        score += 6
        issues.append({"type": "link_count", "value": "Message contains more than eight links.", "weight": 6})
        recommendations.append("Reduce links to the essential call to action and support links.")
    if any(link.startswith("http://") for link in external_links):
        score += 7
        issues.append({"type": "insecure_link", "value": "Message contains an HTTP link.", "weight": 7})
        recommendations.append("Use HTTPS for every email link.")

    if normalized_type == "marketing" and not re.search(r"unsubscribe|opt.?out", searchable):
        score += 15
        issues.append({"type": "unsubscribe", "value": "No unsubscribe language was found.", "weight": 15})
        recommendations.append("Include a working unsubscribe link in every marketing message.")

    if not re.search(r"<html|<body|<p|<div", html_body, re.IGNORECASE):
        score += 3
        issues.append({"type": "html_structure", "value": "HTML appears to have little structure.", "weight": 3})

    if not recommendations:
        recommendations.append("Authenticate the sender domain with SPF, DKIM, and DMARC before sending.")
    recommendations.extend([
        "Send only to consented recipients and suppress bounces, complaints, and unsubscribes.",
        "Warm up new sending domains gradually and monitor provider delivery events.",
    ])

    score = min(score, 100)
    return {
        "risk_score": score,
        "risk_level": "low" if score < 15 else "medium" if score < 35 else "high",
        "issues": issues,
        "recommendations": list(dict.fromkeys(recommendations)),
        "link_count": len(external_links),
        "disclaimer": "This is a heuristic preflight score, not a guarantee of inbox placement.",
    }
