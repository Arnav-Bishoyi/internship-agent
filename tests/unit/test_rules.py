import unittest

from internship_agent.duplicates import compare
from internship_agent.matching import evaluate
from internship_agent.models import Job, Review
from internship_agent.profile import documents


class Rules(unittest.TestCase):
    def setUp(self):
        self.job = Job(
            "Example",
            "Software Intern",
            "https://careers.example.org/jobs/123",
            "123",
            "India",
            "Summer 2027. Python and SQL.",
        )
        self.row = {
            "Company": "Example",
            "Role": "Software Intern (ID: 123), Summer 2027",
            "Status": "Rejected",
        }

    def test_prior_rejection(self):
        self.assertEqual(compare(self.job, [self.row]).kind, "duplicate")

    def test_distinct(self):
        self.assertEqual(
            compare(
                self.job, [self.row | {"Role": "Software Intern ID: 345 Summer 2027"}]
            ).kind,
            "clear",
        )

    def test_prior_term(self):
        self.assertEqual(
            compare(
                self.job, [self.row | {"Role": "Software Intern ID: 123 Summer 2026"}]
            ).kind,
            "clear",
        )

    def test_ambiguous(self):
        self.assertEqual(
            compare(
                self.job,
                [self.row | {"Role": "Software Intern", "Date Applied": "Nov 2026"}],
            ).kind,
            "review",
        )

    def test_planned(self):
        self.assertEqual(
            compare(self.job, [self.row | {"Status": "Saved"}]).kind, "planned"
        )

    def test_graduation(self):
        p = {"may_2029_accurate": True}
        self.assertEqual(documents("Graduating after May 2028", p), 2029)
        self.assertEqual(documents("Graduate between May 2028 and May 2029", p), 2028)
        with self.assertRaises(Review):
            documents("Graduate after May 2028", {})

    def test_location(self):
        p = {"evidence": {"python": "Python project", "sql": "SQL project"}}
        self.assertEqual(evaluate(self.job, p, {"swe": ["software"]})[0], "eligible")
        self.job.location = "United States"
        self.job.description += " We will not provide future sponsorship."
        self.assertEqual(evaluate(self.job, p, {"swe": ["software"]})[0], "skip")

    def test_multiple_graduation_constraints(self):
        p = {"may_2029_accurate": True}
        self.assertEqual(documents("Graduation after May 2028 preferred.", p), 2028)
        with self.assertRaises(Review):
            documents("Graduate after May 2028. Graduate before May 2029.", p)
        self.assertEqual(documents("Graduating on or before May 2029.", p), 2028)

    def test_source_note_mentions_several_requisitions(self):
        row = self.row | {
            "Role": "Software Intern Summer 2027",
            "Notes / Source": "ID: 123, also distinct from ID: 456",
        }
        self.assertEqual(compare(self.job, [row]).kind, "review")

    def test_same_url_employer_alias(self):
        row = self.row | {"Company": "Parent Company", "Notes / Source": self.job.url}
        self.assertEqual(compare(self.job, [row]).kind, "review")

    def test_abbreviated_title(self):
        j = Job(
            "Example",
            "Software Engineer Intern",
            "https://careers.example.org/jobs/123",
            "123",
        )
        row = self.row | {"Role": "SWE Intern Summer 2027"}
        self.assertEqual(compare(j, [row]).kind, "review")
