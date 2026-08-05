import unittest

from services.ai_content import (
    AIContentError,
    _email_system_prompt,
    _ensure_html_call_to_action,
    _normalize_draft_placeholders,
)


def draft(body: str, subject: str = "Your invoice is ready") -> dict:
    return {
        "subject": subject,
        "subject_variants": [subject, "Invoice available", "Invoice notice"],
        "html_body": f"<p>{body}</p>",
        "text_body": body,
    }


class AIContentPlaceholderTests(unittest.TestCase):
    def test_transactional_prompt_excludes_marketing_and_unsubscribe(self):
        prompt = _email_system_prompt("transactional")
        self.assertIn("transactional message", prompt)
        self.assertIn("Do not add promotions", prompt)
        self.assertIn("Do not add promotions, marketing language, or an unsubscribe placeholder", prompt)

    def test_marketing_prompt_requires_conditional_unsubscribe_handling(self):
        prompt = _email_system_prompt("marketing")
        self.assertIn("unsubscribe_url", prompt)

    def test_double_braces_are_normalized_to_single_braces(self):
        result = _normalize_draft_placeholders(
            draft("Hello {{first_name}}"), ["first_name"]
        )
        self.assertEqual(result["text_body"], "Hello {first_name}")
        self.assertEqual(result["html_body"], "<p>Hello {first_name}</p>")

    def test_invented_variable_is_rejected(self):
        with self.assertRaisesRegex(AIContentError, "Email"):
            _normalize_draft_placeholders(draft("Hello {UnknownEmail}"), ["first_name"])

    def test_capitalized_email_alias_is_normalized(self):
        result = _normalize_draft_placeholders(
            draft("Open https://example.com/?email={{Email}}"), ["email"]
        )
        self.assertEqual(
            result["text_body"], "Open https://example.com/?email={email}"
        )

    def test_subject_variable_is_rejected(self):
        with self.assertRaisesRegex(AIContentError, "subject"):
            _normalize_draft_placeholders(
                draft("Hello {first_name}", "Invoice for {first_name}"), ["first_name"]
            )

    def test_html_cta_is_added_to_html_and_text_bodies(self):
        result = _ensure_html_call_to_action(
            draft("Hello {first_name}"),
            '<a href="https://example.com/?email={Email}">View your invoice</a>',
        )
        self.assertIn(
            '<a href="https://example.com/?email={Email}">View your invoice</a>',
            result["html_body"],
        )
        self.assertIn(
            "View your invoice: https://example.com/?email={Email}",
            result["text_body"],
        )

    def test_insecure_html_cta_is_rejected(self):
        with self.assertRaisesRegex(AIContentError, "HTTPS"):
            _ensure_html_call_to_action(
                draft("Hello"), '<a href="http://example.com">View invoice</a>'
            )


if __name__ == "__main__":
    unittest.main()
