import json
import logging
import re
import time
from datetime import datetime

import requests

from .applications.form import receipt, recipe, session, verify_challenge
from .discovery.employer_boards import fetch
from .discovery.shared_roles import resolve
from .integrations.gmail import Gmail
from .integrations.sheets import Sheets
from .matching import evaluate
from .models import Job, Review

LOG = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, config, sheets=None, gmail=None):
        self.s = store
        self.c = config
        self._sheets = sheets
        self._gmail = gmail
        self.fresh_job = self.refresh_posting

    def sheets(self):
        if self._sheets is None:
            self._sheets = Sheets(self.c)
        return self._sheets

    def gmail(self):
        if self._gmail is None:
            self._gmail = Gmail()
        return self._gmail

    def block(self, j, reason, uncertain=False):
        with self.s.transaction():
            if not uncertain:
                self.s.state(j.key, "review")
            self.s.block(
                j.key,
                {
                    "company": j.company,
                    "title": j.title,
                    "url": j.url,
                    "deadline": j.deadline,
                    "reason": str(reason),
                    "uncertain": uncertain,
                },
            )

    def scan_board(self, board):
        for job in fetch(board):
            if re.search(r"\bintern(?:s|ship|ships)?\b", job.title, re.I):
                self.s.job(job, board["type"] + " board")

    def resolve_inbox(self):
        records = [json.loads(r[0]) for r in self.s.db.execute("SELECT data FROM jobs")]
        for lead in self.s.db.execute(
            "SELECT * FROM inbox WHERE state IN ('new','review')"
        ).fetchall():
            found = resolve(lead, records)
            with self.s.transaction():
                if found:
                    self.s.source(found.key, lead["source"], lead["url"])
                    if self.s.db.execute(
                        "UPDATE issues SET closed=1 WHERE id=? AND closed=0",
                        (lead["id"],),
                    ).rowcount:
                        self.s.emit("close", lead["id"], {})
                elif lead["state"] == "review":
                    continue
                else:
                    self.s.block(
                        lead["id"],
                        {
                            "company": "",
                            "title": lead["details"][:160] or "Shared internship",
                            "url": lead["url"],
                            "deadline": "",
                            "reason": "Find the official employer listing or resend /role with the exact employer and title. Apply manually if campus-only.",
                            "uncertain": False,
                        },
                    )
                self.s.db.execute(
                    "UPDATE inbox SET state=? WHERE id=?",
                    ("matched" if found else "review", lead["id"]),
                )

    def guard(self, j):
        try:
            check = self.sheets().check(j)
        except Exception:
            with self.s.transaction():
                self.s.block(
                    "tracker-connection",
                    {
                        "company": "",
                        "title": "Live tracker check failed",
                        "url": "",
                        "deadline": "",
                        "reason": "Check Google OAuth, the tracker header, and Sheets connectivity. Submissions resume after a successful live read.",
                        "uncertain": False,
                    },
                )
            raise
        with self.s.transaction():
            if self.s.db.execute(
                "UPDATE issues SET closed=1 WHERE id='tracker-connection' AND closed=0"
            ).rowcount:
                self.s.emit("close", "tracker-connection", {})
        if check.kind == "duplicate":
            self.s.state(j.key, "duplicate", preview={"tracker_row": check.row})
        if check.kind == "review":
            self.block(
                j, f"Compare this posting with tracker row {check.row} before applying."
            )
        return check

    def prepare(self, j):
        try:
            outcome, score, evidence, year = evaluate(
                j, self.c["profile"], self.c["families"]
            )
            if outcome != "eligible":
                self.s.state(j.key, outcome, score)
                return
            check = self.guard(j)
            if check.kind not in ("clear", "planned"):
                return
            form = recipe(j, self.c["forms"])
            with session(j, form, self.c["profile"], self.c["answers"], year) as (
                _,
                values,
                __,
                ___,
            ):
                self.s.state(
                    j.key,
                    "ready",
                    score,
                    {
                        "fit": evidence,
                        "resume_year": year,
                        "fields": values,
                        "tracker": check.kind,
                        "tracker_row": check.row,
                        "prepared": time.time(),
                    },
                )
        except Review as e:
            self.block(j, e)

    def refresh_posting(self, j):
        for board in self.c["boards"]:
            if board["company"] == j.company:
                for current in fetch(board):
                    if current.key == j.key and current.url == j.url:
                        return current
        raise Review("Confirm that the same employer requisition is still open.")

    def submit_ready(self, j):
        # Recheck employer requirements even between half-hour discovery scans.
        try:
            fresh = self.fresh_job(j)
            if fresh.data() != j.data():
                self.s.job(fresh, "Employer recheck")
                self.s.state(j.key, "new")
                return
            outcome, _, _, year = evaluate(j, self.c["profile"], self.c["families"])
            if outcome != "eligible":
                self.s.state(j.key, outcome)
                return
            form = recipe(j, self.c["forms"])
            with session(
                j, form, self.c["profile"], self.c["answers"], year, live=True
            ) as (page, values, validate, click):
                old = json.loads(
                    self.s.db.execute(
                        "SELECT preview FROM jobs WHERE id=?", (j.key,)
                    ).fetchone()[0]
                )
                if values != old.get("fields"):
                    raise Review(
                        "Review the changed answers or documents before submission."
                    )
                validate()
                if not self.s.reserve(j):
                    return
                try:
                    check = self.guard(j)
                except BaseException:
                    self.release(j, "new")
                    raise
                if check.kind not in ("clear", "planned") or not self.s.get("live"):
                    self.release(
                        j,
                        {"duplicate": "duplicate", "review": "review"}.get(
                            check.kind, "new"
                        ),
                    )
                    return
                started = time.time()
                try:
                    click()
                    if form.get("verification"):
                        verify_challenge(
                            page,
                            form["verification"],
                            self.gmail,
                            self.c["answers"]["email"],
                            started,
                            j,
                        )
                    if receipt(page, j, form["receipt"]):
                        self.s.confirm(
                            j, "Employer confirmation page matched the opening"
                        )
                        return
                except Exception:
                    pass
                self.block(
                    j,
                    "Check for the employer receipt before taking any further action.",
                    True,
                )
        except Review as e:
            self.block(j, e)

    def release(self, j, state):
        with self.s.transaction():
            self.s.db.execute(
                "UPDATE attempts SET state='released' WHERE job=? AND state='pending'",
                (j.key,),
            )
            # guard() has already recorded row evidence on a duplicate.
            if state not in ("duplicate", "review"):
                self.s.state(j.key, state)

    def reconcile(self):
        sql = "SELECT j.data,a.started FROM attempts a JOIN jobs j ON j.id=a.job WHERE a.state='pending'"
        for row in self.s.db.execute(sql).fetchall():
            j = Job(**json.loads(row[0]))
            self.block(
                j,
                "Check for the employer receipt before taking any further action.",
                True,
            )
            try:
                form = recipe(j, self.c["forms"])
            except Review:
                continue
            r = form.get("email_receipt")
            if r and self.gmail().has_receipt(r, self.c["answers"]["email"], row[1], j):
                self.s.confirm(j, "Authenticated employer receipt matched this opening")

    def decisions(self):
        for row in self.sheets().actions():
            key = row.get("Agent ID")
            choice = row.get("Decision", "").strip()
            if choice not in {"Applied manually", "Resolved — resume", "Skip"}:
                continue
            issue = self.s.db.execute(
                "SELECT * FROM issues WHERE id=? AND closed=0", (key,)
            ).fetchone()
            if not issue:
                continue
            record = self.s.db.execute(
                "SELECT data,state FROM jobs WHERE id=?", (key,)
            ).fetchone()
            if not record and choice == "Applied manually":
                # Without employer identity an intake URL alone cannot update application history.
                if not any(
                    row["Link"] in r.get("Notes / Source", "")
                    and (
                        r.get("Date Applied")
                        or r.get("Status", "").lower() == "applied"
                    )
                    for r in self.sheets().rows()
                ):
                    continue
            if record:
                j = Job(**json.loads(record[0]))
                if record[1] == "pending" and choice == "Resolved — resume":
                    # An uncertain click is never rearmed by a generic resume command.
                    continue
            with self.s.transaction():
                if record:
                    if choice == "Applied manually":
                        self.s.db.execute(
                            "UPDATE attempts SET state='confirmed',evidence='Manual confirmation' WHERE job=? AND state='pending'",
                            (key,),
                        )
                        self.s.state(key, "confirmed")
                        self.s.emit(
                            "applied",
                            key,
                            {
                                "job": j.data(),
                                "evidence": "Applicant confirmed manual submission",
                                "date": datetime.now().astimezone().date().isoformat(),
                            },
                        )
                    elif choice == "Skip":
                        self.s.state(key, "skip")
                        self.s.db.execute(
                            "UPDATE attempts SET state='closed' WHERE job=? AND state='pending'",
                            (key,),
                        )
                    else:
                        self.s.state(key, "new")
                else:
                    self.s.db.execute(
                        "UPDATE inbox SET state=? WHERE id=?",
                        ("new" if choice == "Resolved — resume" else "closed", key),
                    )
                self.s.db.execute("UPDATE issues SET closed=1 WHERE id=?", (key,))
            # Clear the consumed command to prevent replays if the issue recurs.
            rows = self.sheets().actions()
            n = next(
                (
                    n
                    for n, r in enumerate(rows, 2)
                    if r.get("Agent ID") == key and r.get("Decision") == choice
                ),
                None,
            )
            if n:
                self.sheets().update("Needs Action", [(f"H{n}", "Handled")])

    def deliver(self, token):
        for row in self.s.db.execute(
            "SELECT * FROM outbox WHERE done=0 AND due<=? ORDER BY id LIMIT 50",
            (time.time(),),
        ).fetchall():
            payload = json.loads(row["payload"])
            try:
                if row["kind"] == "close":
                    self.sheets().close_issue(row["subject"])
                elif row["kind"] == "applied":
                    payload["sources"] = ", ".join(
                        r[0]
                        for r in self.s.db.execute(
                            "SELECT source FROM sources WHERE job=?", (row["subject"],)
                        )
                    )
                    self.sheets().applied(payload)
                    self.s.set("receipt_synced", True)
                else:
                    active = self.s.db.execute(
                        "SELECT closed,body FROM issues WHERE id=?", (row["subject"],)
                    ).fetchone()
                    if active and not active[0] and json.loads(active[1]) == payload:
                        if row["kind"] == "issue":
                            self.sheets().issue(row["subject"], payload)
                        else:
                            self.send_discord(payload, token, row["id"])
            except Exception as e:
                if row["kind"] == "applied" and isinstance(e, Review):
                    job = Job(**payload["job"])
                    with self.s.transaction():
                        self.s.block(
                            job.key,
                            {
                                "company": job.company,
                                "title": job.title,
                                "url": job.url,
                                "deadline": job.deadline,
                                "reason": str(e),
                                "uncertain": False,
                            },
                        )
                LOG.warning("Delivery %s deferred (%s)", row["id"], type(e).__name__)
                delay = min(3600, 30 * 2 ** min(row["tries"], 7))
                self.s.db.execute(
                    "UPDATE outbox SET tries=tries+1,due=? WHERE id=?",
                    (time.time() + delay, row["id"]),
                )
            else:
                self.s.db.execute("UPDATE outbox SET done=1 WHERE id=?", (row["id"],))

    def send_discord(self, p, token, nonce):
        if not token:
            raise RuntimeError("Discord configuration required")
        text = f"{p['company']} · {p['title']}\n{p['reason']}\n{p['url']}\nDeadline: {p['deadline'] or 'unknown'} · Possibly submitted: {'yes' if p['uncertain'] else 'no'}"
        r = requests.post(
            "https://discord.com/api/v10/channels/"
            + str(self.c["discord"]["channel"])
            + "/messages",
            headers={"Authorization": "Bot " + token},
            json={
                "content": text[:1950],
                "allowed_mentions": {"parse": []},
                "nonce": str(nonce),
                "enforce_nonce": True,
            },
            timeout=15,
        )
        r.raise_for_status()

    def due(self, key, interval, action):
        now = time.time()
        if now < self.s.get("next:" + key, 0):
            return
        try:
            action()
        except Exception as e:
            LOG.warning("%s deferred (%s)", key, type(e).__name__)
            self.s.set("next:" + key, now + min(180, interval))
            self.s.set("error:" + key, type(e).__name__)
        else:
            self.s.set("next:" + key, now + interval)
            self.s.set("error:" + key, None)

    def tick(self, token=None):
        for b in self.c["boards"]:
            self.due("board:" + b["company"], 1800, lambda: self.scan_board(b))
        self.due("gmail", 43200, lambda: self.gmail().scan(self.s))
        self.resolve_inbox()
        self.due("actions", 90, self.decisions)
        self.due("reconcile", 120, self.reconcile)

        def prepare_batch():
            for r in self.s.db.execute(
                "SELECT data FROM jobs WHERE state='new' ORDER BY rowid LIMIT 100"
            ).fetchall():
                self.prepare(Job(**json.loads(r[0])))

        self.due("prepare", 20, prepare_batch)
        self.deliver(token)
        if self.s.get("live", False):

            def submit():
                row = self.s.db.execute(
                    "SELECT data FROM jobs WHERE state='ready' ORDER BY score DESC,rowid LIMIT 1"
                ).fetchone()
                if row:
                    self.submit_ready(Job(**json.loads(row[0])))

            self.due("submit", 60, submit)
        self.due(
            "backup",
            86400,
            lambda: self.s.backup(self.s.path.with_suffix(".backup.sqlite")),
        )
