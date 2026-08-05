import unittest

from services.transactional_email import TransactionalEmailError, render_variables


class TemplateVariableTests(unittest.TestCase):
    def test_single_brace_placeholder_is_rendered_without_braces(self):
        self.assertEqual(render_variables("Hello {first_name}", {"first_name": "Arif"}), "Hello Arif")

    def test_double_brace_placeholder_is_rendered_without_braces(self):
        self.assertEqual(render_variables("Hello {{first_name}}", {"first_name": "Arif"}), "Hello Arif")

    def test_missing_double_brace_placeholder_is_reported(self):
        with self.assertRaisesRegex(TransactionalEmailError, "first_name"):
            render_variables("Hello {{first_name}}", {})

    def test_capitalized_email_alias_is_rendered_inside_link(self):
        content = '<a href="https://example.com/?email={Email}">View</a>'
        self.assertEqual(
            render_variables(content, {"email": "arif@example.com"}),
            '<a href="https://example.com/?email=arif@example.com">View</a>',
        )


if __name__ == "__main__":
    unittest.main()
