import json
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from ..models import Job, canonical


def plain(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ",strip=True)


def fetch(board):
    company=board["company"]
    kind=board["type"]
    slug=board.get("slug","")
    if kind=="greenhouse":
        response=requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",params={"content":"true"},timeout=25)
        response.raise_for_status()
        for x in response.json()["jobs"]:
            import html
            yield Job(company,x["title"],canonical(x["absolute_url"]),str(x.get("requisition_id") or x["id"]),
                      x["location"]["name"],plain(html.unescape(x.get("content",""))),x.get("first_published") or "")
    elif kind=="lever":
        offset=0
        while True:
            response=requests.get(f"https://api.lever.co/v0/postings/{slug}",
                                  params={"mode":"json","skip":offset,"limit":100},timeout=25)
            response.raise_for_status()
            page=response.json()
            for x in page:
                desc=" ".join([x.get("descriptionPlain",""),*(plain(l["content"]) for l in x.get("lists",[])),x.get("additionalPlain","") or ""])
                loc=x.get("categories",{})
                yield Job(company,x["text"],canonical(x["hostedUrl"]),x["id"],
                          ", ".join(filter(None,[loc.get("location"),x.get("country")])),desc,
                          datetime.fromtimestamp(x["createdAt"]/1000,timezone.utc).isoformat() if x.get("createdAt") else "")
            if len(page)<100:
                break
            offset+=100
    elif kind=="careers":
        # Only URLs explicitly configured by the operator are fetched.
        for url in board["urls"]:
            response=requests.get(canonical(url),timeout=25,allow_redirects=False)
            response.raise_for_status()
            for script in BeautifulSoup(response.text,"html.parser").select('script[type="application/ld+json"]'):
                raw=json.loads(script.get_text())
                items=raw if isinstance(raw,list) else raw.get("@graph",[raw])
                for x in items:
                    if x.get("@type")!="JobPosting":
                        continue
                    loc=x.get("jobLocation",[])
                    locations=loc if isinstance(loc,list) else [loc]
                    country=", ".join(str(y.get("address",{}).get("addressCountry","")) for y in locations)
                    identifier=x.get("identifier",{})
                    yield Job(company,x["title"],canonical(x.get("url") or url),
                              str(identifier.get("value","") if isinstance(identifier,dict) else identifier),
                              country,plain(x["description"]),x.get("datePosted",""),x.get("validThrough",""))
    else:
        raise ValueError("Unknown board type")
