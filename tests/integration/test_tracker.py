import unittest

from internship_agent.duplicates import HEADERS
from internship_agent.integrations.sheets import Sheets
from internship_agent.models import Job


class TrackerWrites(unittest.TestCase):
    def test_retry_after_confirmed_write(self):
        j = Job("Example", "Software Intern", "https://careers.example.org/1", "1")
        p = {"job": j.data(), "date": "2026-11-23", "evidence": "Receipt matched"}
        tracker = object.__new__(Sheets)
        data = []
        tracker.tab = "Existing"
        tracker.rows = lambda: data
        tracker.append = lambda tab, row: data.append(dict(zip(HEADERS, row)))
        tracker.applied(p)
        tracker.applied(p)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["Status"], "Applied")
        self.assertEqual(tracker.check(j).kind, "duplicate")

    def test_planned_row_preserves_notes(self):
        j = Job("Example", "Software Intern", "https://careers.example.org/1", "1")
        tracker = object.__new__(Sheets)
        tracker.rows = lambda: [
            {
                "Company": "Example",
                "Role": "Software Intern (ID: 1) Summer 2027",
                "Status": "Planned",
                "Notes / Source": "my note",
            }
        ]
        tracker.tab = "Existing"
        writes = []
        tracker.update = lambda tab, changes: writes.extend(changes)
        tracker.applied(
            {"job": j.data(), "date": "2026-11-23", "evidence": "Receipt matched"}
        )
        self.assertTrue(dict(writes)["K2"].startswith("my note\n"))
        self.assertEqual(dict(writes)["E2"], "Applied")
