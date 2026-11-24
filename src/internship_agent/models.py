import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def norm(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def canonical(url):
    p = urlsplit(url.strip())
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        raise ValueError("Expected an HTTPS job URL")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not k.lower().startswith("utm_")
        and k.lower() not in {"trk", "trackingid", "refid", "gh_src"}
    ]
    return urlunsplit(
        (
            "https",
            p.hostname.lower(),
            p.path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


@dataclass
class Job:
    company: str
    title: str
    url: str
    req: str = ""
    location: str = ""
    description: str = ""
    posted: str = ""
    deadline: str = ""
    cycle: str = "Summer 2027"

    @property
    def key(self):
        identity = self.req.casefold() or canonical(self.url)
        return sha256(
            f"{norm(self.company)}|{identity}|{self.cycle}".encode()
        ).hexdigest()[:24]

    def identifies(self, text):
        identifier = re.escape(self.req or self.title)
        return bool(re.search(r"(?<!\w)" + identifier + r"(?!\w)", text, re.I))

    def data(self):
        return asdict(self)


class Review(Exception):
    """A human-readable next step suitable for the private blocker queue."""
