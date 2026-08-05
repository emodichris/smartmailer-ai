import unittest

from app import transactional_recipients_from_csv, validate_transactional_csv_recipients


class TransactionalCSVTests(unittest.TestCase):
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
