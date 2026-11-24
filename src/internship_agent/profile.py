import calendar
import re
from pathlib import Path

from .models import Review

MONTHS = {name.casefold(): n for n, name in enumerate(calendar.month_name) if name}
DATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", re.I)


def graduation_window(sentence, dates):
    if len(dates) == 2 and re.search(r"between|\bto\b|through|[-–—]", sentence, re.I):
        return lambda date: dates[0] <= date <= dates[1]
    if len(dates) != 1:
        raise Review("Confirm the graduation window.")
    cutoff = dates[0]
    for expression, accepts in (
        (r"on or after|or later|no earlier than|at least", lambda d: d >= cutoff),
        (r"on or before|no later than|by\b|or earlier", lambda d: d <= cutoff),
        (r"\bafter|later than", lambda d: d > cutoff),
        (r"\bbefore|earlier than", lambda d: d < cutoff),
    ):
        if re.search(expression, sentence, re.I):
            return accepts
    return lambda d: d == cutoff


def documents(text, profile):
    possible = {2028, 2029}
    for sentence in re.split(r"[.;\n]", text):
        if not re.search(r"graduat|class of", sentence, re.I):
            continue
        if re.search(r"prefer(?:red|ably)|nice to have", sentence, re.I):
            continue
        dates = [(int(y), MONTHS[m.lower()]) for m, y in DATE.findall(sentence)]
        if dates:
            accepts = graduation_window(sentence, dates)
            possible = {y for y in possible if accepts((y, 5))}
        elif re.search(r"20\d\d|final.year|penultimate", sentence, re.I):
            raise Review("Confirm the class-year requirement on the posting.")
    if 2028 in possible:
        return 2028
    if 2029 in possible and profile.get("may_2029_accurate") is True:
        return 2029
    raise Review("Confirm that your academic plan meets the graduation window.")


def pdf(profile, key):
    path = Path(profile["documents"][key]).expanduser()
    if path.is_file():
        with path.open("rb") as file:
            if file.read(5) == b"%PDF-":
                return path
    raise Review("Check the local PDF configured for " + key + ".")
