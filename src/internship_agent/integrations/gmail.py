import base64
import email
import re
import time
from email.policy import default
from email.utils import getaddresses
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .google import client
from ..discovery.linkedin_alerts import ingest
from ..models import canonical


def addresses(msg,field):
    return {v.lower() for _,v in getaddresses(msg.get_all(field,[]))}


def body(msg):
    part=msg.get_body(preferencelist=("html","plain"))
    return part.get_content() if part else ""


def authenticated(msg,sender):
    # Trust the receiving Gmail server's Authentication-Results, and match its DMARC identity.
    result=next((str(x) for x in msg.get_all("Authentication-Results",[]) if str(x).lstrip().startswith("mx.google.com;")),"")
    domain=sender.rpartition("@")[2].lower()
    return bool(re.search(r"\bdmarc=pass\b[^;]*\bheader\.from="+re.escape(domain)+r"(?:\s|;|$)",result,re.I))


class Gmail:
    def __init__(self):
        self.api=client("gmail","v1").users().messages()

    def messages(self,query):
        token=None
        while True:
            batch=self.api.list(userId="me",q=query,pageToken=token,maxResults=100).execute()
            for entry in batch.get("messages",[]):
                r=self.api.get(userId="me",id=entry["id"],format="raw").execute()
                msg=email.message_from_bytes(base64.urlsafe_b64decode(r["raw"]),policy=default)
                yield r["id"],int(r["internalDate"])/1000,msg
            token=batch.get("nextPageToken")
            if not token: break

    def scan(self,store):
        now=int(time.time())
        start=store.get("gmail_cursor",now-10*86400)
        for mid,_,msg in self.messages(f"after:{start-1} before:{now+1} from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com)"):
            senders=addresses(msg,"From")
            if any(authenticated(msg,s) for s in senders & {"jobalerts-noreply@linkedin.com","jobs-noreply@linkedin.com"}):
                ingest(store,mid,body(msg))
        store.set("gmail_cursor",now)

    def verification(self,rule,recipient,started):
        sender=rule["sender"].lower()
        hits=[]
        for mid,stamp,msg in self.messages(f"after:{int(started)-1} from:{sender} to:{recipient}"):
            if not started<=stamp<=time.time() or time.time()-stamp>300: continue
            if addresses(msg,"From")!={sender} or recipient.lower() not in addresses(msg,"To"): continue
            if not authenticated(msg,sender) or not re.fullmatch(rule["subject"],str(msg.get("Subject",""))): continue
            data=body(msg)
            if rule["kind"]=="code":
                values=set(re.findall(rule["pattern"],BeautifulSoup(data,"html.parser").get_text(" ",strip=True)))
            else:
                values=set()
                for a in BeautifulSoup(data,"html.parser").select("a[href]"):
                    try: url=canonical(a["href"])
                    except ValueError: continue
                    if urlsplit(url).hostname in rule["hosts"] and re.fullmatch(rule["path"],urlsplit(url).path):
                        values.add(a["href"])
            if len(values)==1: hits.append((mid,values.pop()))
            elif values: return None
        return hits[0] if len(hits)==1 else None

    def has_receipt(self,rule,recipient,started,job):
        sender=rule["sender"].lower()
        for _,stamp,msg in self.messages(f"after:{int(started)-1} from:{sender} to:{recipient}"):
            if stamp<started or addresses(msg,"From")!={sender} or recipient.lower() not in addresses(msg,"To"): continue
            if not authenticated(msg,sender) or not re.fullmatch(rule["subject"],str(msg.get("Subject",""))): continue
            text=BeautifulSoup(body(msg),"html.parser").get_text(" ",strip=True)
            if re.search(rule["pattern"],text,re.I) and (job.req or job.title).casefold() in text.casefold(): return True
        return False
