"""Safe in-memory CSV parsing for workspace contacts."""

from __future__ import annotations

import csv
import io


class ContactCSVError(ValueError):
    pass


def parse_contacts_csv(content: bytes) -> tuple[list[dict[str, str]], int]:
    """Read a UTF-8 CSV with an email column and preserve optional contact fields."""
    if len(content) > 5 * 1024 * 1024:
        raise ContactCSVError("CSV files may not exceed 5 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ContactCSVError("CSV must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ContactCSVError("CSV must include a header row with an email column.")
    columns = {name.strip().lower(): name for name in reader.fieldnames if name}
    email_column = columns.get("email")
    if not email_column:
        raise ContactCSVError("CSV must include a column named email.")

    contacts = []
    total_rows = 0
    for row in reader:
        total_rows += 1
        contact = {
            str(key).strip(): str(value).strip()
            for key, value in row.items()
            if key and value is not None and str(value).strip()
        }
        if email_column in contact:
            contact["email"] = contact.pop(email_column)
        contacts.append(contact)
    return contacts, total_rows
