import tempfile,unittest
from pathlib import Path
from internship_agent.models import Job
from internship_agent.store import Store
from internship_agent.discovery.linkedin_alerts import ingest
from internship_agent.discovery.shared_roles import resolve,shared_url

class Discovery(unittest.TestCase):
    def test_sources(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/"test.db")
            j=Job("Example","Software Intern","https://example.org/careers/42","42")
            s.job(j,"Employer board")
            msg='<p><a href="https://www.linkedin.com/comm/jobs/view/123?trk=mail">Example Software Intern</a></p><p><a href="https://www.linkedin.com/jobs/view/124">Other firm</a></p>'
            ingest(s,"m1",msg)
            ingest(s,"m1",msg)
            link=shared_url("https://school.joinhandshake.com/jobs/22")
            self.assertTrue(s.lead("123",link,"Example Software Intern","Discord"))
            self.assertFalse(s.lead("123",link,"Example Software Intern","Discord"))
            for row in s.db.execute("select * from inbox"):
                hit=resolve(row,[j.data()])
                if hit: s.source(hit.key,row["source"])
            self.assertEqual(s.db.execute("select count(*) from inbox").fetchone()[0],3)
            self.assertEqual(s.db.execute("select count(*) from sources").fetchone()[0],3)
            self.assertIsNone(resolve({"url":link,"details":""},[j.data()]))
            s.db.close()
