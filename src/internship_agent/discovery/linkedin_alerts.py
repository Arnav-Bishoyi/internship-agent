import re
from hashlib import sha256
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from ..models import canonical

JOB_PATH=re.compile(r"^/(?:comm/)?jobs/view/(?:[\w%-]+-)?(\d+)(?:/|$)",re.I)


def linkedin_url(value):
    try:
        url=canonical(value)
        parsed=urlsplit(url)
        if parsed.hostname in {"linkedin.com","www.linkedin.com"}:
            hit=JOB_PATH.match(parsed.path)
            if hit:
                return "https://www.linkedin.com/jobs/view/"+hit[1]
    except ValueError:
        pass
    return ""


def extract(body):
    soup=BeautifulSoup(body,"html.parser")
    leads={}
    for anchor in soup.find_all("a",href=True):
        url=linkedin_url(anchor["href"])
        if url:
            parent=anchor.find_parent("tr") or anchor.parent
            hint=" ".join(parent.stripped_strings)[:900]
            if len(hint)>len(leads.get(url,"")):
                leads[url]=hint
    for raw in re.findall(r'https://[^\s<>"\]]+',body):
        url=linkedin_url(raw)
        if url and url not in leads:
            leads[url]=""
    return leads


def ingest(store,message,body):
    with store.transaction():
        if not store.db.execute("INSERT OR IGNORE INTO seen VALUES(?)",(message,)).rowcount:
            return
        for url,details in extract(body).items():
            key=sha256(("linkedin:"+url).encode()).hexdigest()
            store.lead(key,url,details,"LinkedIn email")
