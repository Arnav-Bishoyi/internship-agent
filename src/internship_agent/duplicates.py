import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import canonical, norm

HEADERS = ("Company","Role","Location","Date Applied","Status","Result","Result Date",
           "To-Do / Next Step","Deadline","Possible Rejection Reasons (researched)","Notes / Source")
ID = re.compile(r"\b(?:req(?:uisition)?(?:\s*id)?|job\s*id|id)\s*[:#-]?\s*([a-z0-9-]*\d[a-z0-9-]*)\b", re.I)
TERM = re.compile(r"\b(summer|fall|autumn|spring|winter)\s*[-/]?\s*(20\d{2})\b", re.I)


@dataclass(frozen=True)
class Check:
    kind: str
    row: int = 0


def org(s):
    return re.sub(r"\s+(inc|llc|ltd|limited|corporation)$", "", norm(s))


def compare(job, rows):
    candidates = []
    for num, row in enumerate(rows, 2):
        if org(row.get("Company", "")) != org(job.company):
            continue
        role = row.get("Role", "")
        notes = row.get("Notes / Source", "")
        # Explanatory notes often mention other, explicitly distinct requisitions.
        primary = re.search(r"(?im)^agent req:\s*(\S+)", notes)
        ids = {primary[1].casefold()} if primary else set(x.casefold() for x in ID.findall(role))
        if not ids:
            ids = set(x.casefold() for x in ID.findall(notes))
        urls = set()
        for url in re.findall(r'https://[^\s<>"\]]+', notes):
            try:
                urls.add(canonical(url.rstrip(".,);")))
            except ValueError:
                pass
        terms = {norm(" ".join(m)).replace("autumn", "fall") for m in TERM.findall(role)}
        if not terms:
            terms = {norm(" ".join(m)).replace("autumn", "fall") for m in TERM.findall(notes)}
        if len(terms) == 1 and norm(job.cycle) not in terms:
            continue
        exact = (bool(job.req) and job.req.casefold() in ids) or canonical(job.url) in urls
        if len(ids) == 1 and job.req and not exact:
            continue
        title = norm(ID.sub("", role))
        similar = (norm(job.title) in title or (bool(title) and title in norm(job.title))
                   or SequenceMatcher(None, norm(job.title), title).ratio() >= 0.70)
        if not (exact or similar):
            continue
        status = norm(row.get("Status", ""))
        result = norm(row.get("Result", ""))
        submitted = bool(row.get("Date Applied") or result or status in {
            "applied","submitted","rejected","withdrawn","interview","interviewing","offer","accepted"})
        planned = status in {"planned","saved","to apply"} and not submitted
        known = terms == {norm(job.cycle)}
        if exact and known and submitted:
            return Check("duplicate", num)
        if exact and known and planned:
            candidates.append(Check("planned", num))
        else:
            candidates.append(Check("review", num))
    if not candidates:
        return Check("clear")
    if len(candidates) == 1:
        return candidates[0]
    return Check("review", candidates[0].row)
