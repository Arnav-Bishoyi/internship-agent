import threading,unittest,tempfile,yaml
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from playwright.sync_api import Route
from internship_agent.models import Job,Review
from internship_agent.applications.form import session,receipt

HTML=b"""<h1 id="opening">Software Intern - 42</h1>
<form id="application" method="post" action="/applications" enctype="multipart/form-data">
<label>Email<input id="email" name="email" required type="email"></label>
<label>Resume<input id="resume" type="file" name="resume" required></label>
<button type="submit">Submit application</button></form>"""

class Browser(unittest.TestCase):
    def test_preview_and_submission(self):
        posts=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def serve(self,data):
                self.send_response(200);self.send_header("Content-Type","text/html");self.end_headers();self.wfile.write(data)
            def do_GET(self): self.serve(HTML)
            def do_POST(self):
                posts.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.serve(b'<p id="confirmation">Application received for 42</p>')
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        original=Route.fetch
        def loopback(route,**kw):
            return original(route,url=f"http://127.0.0.1:{server.server_port}"+urlsplit(route.request.url).path,**kw)
        form=yaml.safe_load(Path("config/form.example.yaml").read_text())
        j=Job("Example","Software Intern","https://careers.example.org/jobs/42","42")
        try:
            with tempfile.TemporaryDirectory() as d,patch.object(Route,"fetch",loopback):
                p=Path(d)/"synthetic.pdf";p.write_bytes(b"%PDF-synthetic")
                profile={"documents":{"resume_2028":str(p)}}
                for live in (False,True):
                    with session(j,form,profile,{"email":"student@example.org"},2028,live=live) as (page,preview,validate,click):
                        self.assertEqual(preview["Resume"],p.name)
                        validate()
                        if live:
                            click()
                            self.assertTrue(receipt(page,j,form["receipt"]))
                        else: self.assertFalse(posts)
                self.assertEqual(len(posts),1)
                self.assertIn(b"%PDF-synthetic",posts[0])
        finally:
            server.shutdown();server.server_close();t.join()
