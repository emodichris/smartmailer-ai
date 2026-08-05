import unittest

from services.ai_content import AIContentError, _normalize_draft_placeholders


def draft(body: str, subject: str = "Your invoice is ready") -> dict:
    return {
        "subject": subject,
        "subject_variants": [subject, "Invoice available", "Invoice notice"],
        "html_body": f"<p>{body}</p>",
        "text_body": body,
    }


class AIContentPlaceholderTests(unittest.TestCase):
    def test_double_braces_are_normalized_to_single_braces(self):
        result = _normalize_draft_placeholders(
            draft("Hello {{first_name}}"), ["first_name"]
        )
        self.assertEqual(result["text_body"], "Hello {first_name}")
        self.assertEqual(result["html_body"], "<p>Hello {first_name}</p>")

    def test_invented_variable_is_rejected(self):
        with self.assertRaisesRegex(AIContentError, "Email"):
            _normalize_draft_placeholders(draft("Hello {Email}"), ["first_name"])

    def test_subject_variable_is_rejected(self):
        with self.assertRaisesRegex(AIContentError, "subject"):
            _normalize_draft_placeholders(
                draft("Hello {first_name}", "Invoice for {first_name}"), ["first_name"]
            )


if __name__ == "__main__":
    unittest.main()
