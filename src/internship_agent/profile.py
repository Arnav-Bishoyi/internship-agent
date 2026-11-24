import calendar
import re
from pathlib import Path
from .models import Review

MONTHS = {name.casefold(): n for n, name in enumerate(calendar.month_name) if name}
DATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b", re.I)


def documents(text, profile):
    year = 2028
    for sentence in re.split(r"[.;\n]", text):
        if not re.search(r"graduat|class of", sentence, re.I):
            continue
        dates = [(int(y), MONTHS[m.lower()]) for m,y in DATE.findall(sentence)]
        if not dates:
            if re.search(r"20\d\d|final.year|penultimate", sentence, re.I):
                raise Review("Confirm the class-year requirement on the posting.")
            continue
        a, b = (2028,5), (2029,5)
        if len(dates) == 2 and re.search(r"between|\bto\b|through|[-–—]",sentence,re.I):
            fits = lambda d: dates[0] <= d <= dates[1]
        elif len(dates) == 1:
            inclusive = re.search(r"on or after|or later|no earlier|at least", sentence,re.I)
            after = re.search(r"after|later than",sentence,re.I)
            before = re.search(r"before|earlier than",sentence,re.I)
            if inclusive:
                fits = lambda d: d >= dates[0]
            elif after and not before:
                fits = lambda d: d > dates[0]
            elif before and not after and not re.search(r"on or before|no later",sentence,re.I):
                fits = lambda d: d < dates[0]
            else:
                fits = lambda d: d == dates[0]
        else:
            raise Review("Confirm the graduation window.")
        if not fits(a):
            if fits(b) and profile.get("may_2029_accurate") is True:
                year = 2029
            else:
                raise Review("Confirm that your academic plan meets the graduation window.")
    return year


def pdf(profile, key):
    path = Path(profile["documents"][key]).expanduser()
    if not path.is_file() or path.read_bytes()[:5] != b"%PDF-":
        raise Review("Check the local PDF configured for " + key + ".")
    return path
