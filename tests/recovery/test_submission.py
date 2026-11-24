import json,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from internship_agent.duplicates import Check
from internship_agent.models import Job
from internship_agent.store import Store
from internship_agent.worker import Worker

class Tracker:
    def __init__(self): self.result=Check("clear"); self.calls=0
    def check(self,j):
        self.calls+=1
        if isinstance(self.result,Exception): raise self.result
        return self.result

class Submission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"db"
        self.s=Store(self.path)
        self.j=Job("Example","Software Intern","https://example.org/jobs/1","1","India","Summer 2027 Python SQL")
        self.c={"profile":{"evidence":{"python":"Python project","sql":"SQL project"}},"answers":{},
                "families":{"swe":["software"]},"forms":[{"company":"Example","permission":"test only","host":"example.org","job_path":"/jobs/1","receipt":{}}]}
        self.tracker=Tracker()
        self.w=Worker(self.s,self.c,sheets=self.tracker)
        self.s.job(self.j,"Board")
        self.s.set("live",True)
        self.clicked=0
        @contextmanager
        def fake(*a,**kw):
            def click(): self.clicked+=1
            yield None,{"field":"answer"},lambda:None,click
        self.patch=patch("internship_agent.worker.session",fake)
        self.patch.start()
        self.w.prepare(self.j)

    def tearDown(self): self.patch.stop();self.s.db.close();self.tmp.cleanup()

    def test_manual_entry_after_preview(self):
        self.tracker.result=Check("duplicate",3)
        self.w.submit_ready(self.j)
        self.assertEqual((self.tracker.calls,self.clicked),(2,0))

    def test_outage_after_preview(self):
        self.tracker.result=ConnectionError()
        with self.assertRaises(ConnectionError): self.w.submit_ready(self.j)
        self.assertEqual(self.clicked,0)
        self.assertEqual(self.s.db.execute("select state from attempts").fetchone()[0],"released")

    def test_crash_before_or_after_click(self):
        self.assertTrue(self.s.reserve(self.j))
        self.s.db.close();self.s=Store(self.path)
        self.w=Worker(self.s,self.c,sheets=self.tracker)
        self.w.reconcile()
        self.assertFalse(self.s.reserve(self.j))
        self.assertEqual(self.s.db.execute("select count(*) from issues").fetchone()[0],1)

    def test_confirm_and_hold(self):
        with patch("internship_agent.worker.receipt",return_value=True):
            self.w.submit_ready(self.j)
        self.assertEqual(self.clicked,1)
        self.assertEqual(self.s.db.execute("select kind from outbox").fetchone()[0],"applied")
        other=Job(**(self.j.data()|{"req":"2"}))
        self.assertFalse(self.s.reserve(other))
        self.s.set("first_receipt_verified",True)
        for i in range(2,6): self.assertTrue(self.s.reserve(Job(**(self.j.data()|{"req":str(i)}))))
        self.assertFalse(self.s.reserve(Job(**(self.j.data()|{"req":"6"}))))
