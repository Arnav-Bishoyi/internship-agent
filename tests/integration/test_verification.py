import time
import unittest
from email.message import EmailMessage

from internship_agent.integrations.gmail import Gmail


class Verification(unittest.TestCase):
    def test_scope_and_time(self):
        g = object.__new__(Gmail)
        msg = EmailMessage()
        msg["From"] = "apply@example.org"
        msg["To"] = "test@example.com"
        msg["Subject"] = "Example job 42"
        msg["Authentication-Results"] = (
            "mx.google.com; dmarc=pass header.from=example.org"
        )
        msg.set_content("Code 123456")
        rule = {
            "sender": "apply@example.org",
            "subject": "Example job 42",
            "kind": "code",
            "pattern": r"\b\d{6}\b",
        }
        now = time.time() - 1
        g.messages = lambda q: [("m", now, msg)]
        self.assertEqual(
            g.verification(rule, "test@example.com", now - 1, "42"), ("m", "123456")
        )
        self.assertIsNone(g.verification(rule, "other@example.com", now - 1, "42"))
        self.assertIsNone(g.verification(rule, "test@example.com", now + 1, "42"))
        self.assertIsNone(
            g.verification(
                rule | {"subject": "Other job"}, "test@example.com", now - 1, "42"
            )
        )
        g.messages = lambda q: [("old", now - 600, msg)]
        self.assertIsNone(g.verification(rule, "test@example.com", now - 700, "42"))

    def test_approved_link_and_conflicting_messages(self):
        g = object.__new__(Gmail)
        msg = EmailMessage()
        msg["From"] = "apply@example.org"
        msg["To"] = "test@example.com"
        msg["Subject"] = "Challenge"
        msg["Authentication-Results"] = (
            "mx.google.com; dmarc=pass header.from=example.org"
        )
        url = "https://careers.example.org/verify?t=synthetic"
        msg.set_content('<a href="' + url + '">Verify</a>', subtype="html")
        rule = {
            "sender": "apply@example.org",
            "subject": "Challenge",
            "kind": "link",
            "hosts": ["careers.example.org"],
            "path": "/verify",
        }
        now = time.time() - 1
        g.messages = lambda q: [("m", now, msg)]
        self.assertEqual(
            g.verification(rule, "test@example.com", now - 1, "Challenge"), ("m", url)
        )
        self.assertIsNone(
            g.verification(
                rule | {"hosts": ["other.example.org"]},
                "test@example.com",
                now - 1,
                "Challenge",
            )
        )
        g.messages = lambda q: [("m", now, msg), ("m2", now, msg)]
        self.assertIsNone(
            g.verification(rule, "test@example.com", now - 1, "Challenge")
        )
