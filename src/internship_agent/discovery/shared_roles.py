from urllib.parse import urlsplit
from ..models import Job,canonical,norm
from .linkedin_alerts import linkedin_url


def shared_url(value):
    url=canonical(value)
    li=linkedin_url(url)
    if li:
        return li
    host=urlsplit(url).hostname
    if host=="joinhandshake.com" or host.endswith(".joinhandshake.com"):
        return url
    raise ValueError("Use a LinkedIn job or Handshake listing link.")


def resolve(lead,records):
    text=norm(lead["details"])
    matches=[]
    for r in records:
        j=Job(**r)
        if canonical(lead["url"])==canonical(j.url):
            return j
        if norm(j.company) in text and norm(j.title) in text:
            matches.append(j)
    if len(matches)==1:
        return matches[0]
    return None
