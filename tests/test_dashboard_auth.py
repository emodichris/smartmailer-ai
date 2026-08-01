import unittest

from services.dashboard_auth import create_session, hash_password, verify_password, verify_session


class DashboardAuthenticationTests(unittest.TestCase):
    def test_password_hash_accepts_only_the_original_password(self):
        encoded = hash_password("correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))

    def test_session_is_signed_without_an_application_expiry(self):
        token = create_session("admin", "session-secret")
        self.assertTrue(verify_session(token, "admin", "session-secret"))
        self.assertFalse(verify_session(token, "other-user", "session-secret"))
        self.assertFalse(verify_session(token, "admin", "wrong-secret"))

    def test_tampered_session_is_rejected(self):
        token = create_session("admin", "session-secret")
        self.assertFalse(verify_session(f"{token}changed", "admin", "session-secret"))


if __name__ == "__main__":
    unittest.main()
