import unittest
from unittest.mock import patch

from app import transactional_recipients_from_csv, validate_transactional_csv_recipients


class TransactionalCSVTests(unittest.TestCase):
    @patch("app.check_receiving_domain_status", return_value="invalid")
    def test_rejects_domain_without_mx(self, _status):
        recipients, invalid, total = transactional_recipients_from_csv(
            b"email,first_name,invoice_number,invoice_url\na@example.invalid,A,1,https://example.com\n",
            verify_domains=True,
        )
        self.assertEqual(total, 1)
        self.assertEqual(recipients, [])
        self.assertEqual(invalid[0]["category"], "invalid_domain")

    def test_csv_is_deduplicated_and_email_link_template_is_resolved(self):
        content = (
            "email,first_name,invoice_number,invoice_url\n"
            "arif@example.com,Arif,82026,https://example.com/?email={Email}\n"
            "ARIF@example.com,Duplicate,82026,https://example.com/?email={Email}\n"
            "invalid,Invalid,82026,https://example.com/?email={Email}\n"
        ).encode()
        recipients, invalid, total = transactional_recipients_from_csv(content)
        self.assertEqual(total, 3)
        self.assertEqual(len(recipients), 1)
        self.assertEqual(len(invalid), 2)
        self.assertEqual(
            recipients[0]["variables"]["invoice_url"],
            "https://example.com/?email=arif@example.com",
        )

    def test_invoice_template_requirements_are_validated_before_queueing(self):
        content = (
            "email,first_name,invoice_number,invoice_url\n"
            "arif@example.com,Arif,82026,https://example.com/invoice\n"
        ).encode()
        recipients, invalid, _ = transactional_recipients_from_csv(content)
        valid = validate_transactional_csv_recipients(recipients, invalid, "invoice")
        self.assertEqual(len(valid), 1)
        self.assertFalse(invalid)

    def test_missing_invoice_value_is_rejected_before_queueing(self):
        content = (
            "email,first_name,invoice_number\n"
            "arif@example.com,Arif,82026\n"
        ).encode()
        recipients, invalid, _ = transactional_recipients_from_csv(content)
        valid = validate_transactional_csv_recipients(recipients, invalid, "invoice")
        self.assertFalse(valid)
        self.assertIn("invoice_url", invalid[0]["reason"])


if __name__ == "__main__":
    unittest.main()
