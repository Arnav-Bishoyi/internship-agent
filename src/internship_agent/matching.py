from datetime import datetime, timezone
import re
from .models import Review
from .profile import documents


def evaluate(job, profile, families):
    title = job.title.casefold()
    text = (job.title + "\n" + job.description).casefold()
    country = job.location.casefold()
    if "intern" not in text or not any(w in title for words in families.values() for w in words):
        return "skip", 0, [], 0
    if not re.search(r"summer\s+(?:of\s+)?2027|2027\s+summer", text):
        raise Review("Confirm the Summer 2027 internship term.")
    us = bool(re.search(r"united states|\bu\.?s\.?a?\b", country))
    india = bool(re.search(r"\bindia\b", country))
    if us == india:
        raise Review("Confirm the physical work country.")
    if us and re.search(r"(?:no|without|cannot|unable to|will not|do not|does not|not (?:eligible|available))[^.;\n]{0,65}(?:sponsor|\bcpt\b)|(?:sponsorship|cpt)[^.;\n]{0,40}(?:not (?:offered|available|accepted|supported)|ineligible)|(?:us|u\.s\.) citizens? only", text):
        return "skip", 0, ["US authorization requirement"], 0
    if re.search(r"\b(?:clearance|ph\.?d|masters? degree required|citizenship required|export control|sponsorship|\bcpt\b)\b", text):
        raise Review("Verify employer-specific eligibility wording.")
    year = documents(text, profile)
    evidence = [v for k,v in profile.get("evidence",{}).items()
                if re.search(r"(?<!\w)"+re.escape(k.casefold())+r"(?!\w)",text)]
    score = min(len(evidence), 5)*10
    try:
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(job.posted.replace("Z","+00:00"))).days
        score += 5 if 0 <= age <= 7 else 0
    except (TypeError,ValueError):
        pass
    return ("eligible" if len(evidence)>=2 else "low_fit"), score, evidence, year
