import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(path, timeout=20, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'new',score INTEGER DEFAULT 0,preview TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS sources(job TEXT, source TEXT, PRIMARY KEY(job,source));
        CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,url TEXT,details TEXT,source TEXT,state TEXT DEFAULT 'new');
        CREATE TABLE IF NOT EXISTS source_links(job TEXT,source TEXT,url TEXT,PRIMARY KEY(job,source,url));
        CREATE INDEX IF NOT EXISTS inbox_url ON inbox(url,source);
        CREATE TABLE IF NOT EXISTS seen(message TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,job TEXT,day TEXT,state TEXT,started REAL,evidence TEXT);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,kind TEXT,subject TEXT,payload TEXT,
            done INTEGER DEFAULT 0,tries INTEGER DEFAULT 0,due REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS issues(id TEXT PRIMARY KEY,subject TEXT,body TEXT,opened REAL,closed INTEGER DEFAULT 0);
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        self.db.execute(
            "INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v))
        )

    def job(self, j, source):
        self.db.execute(
            """INSERT INTO jobs(id,data) VALUES(?,?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data,
            state=CASE WHEN jobs.data != excluded.data AND jobs.state IN ('ready','skip','low_fit')
            THEN 'new' ELSE jobs.state END""",
            (j.key, json.dumps(j.data())),
        )
        self.source(j.key, source, j.url)

    def source(self, key, source, url=None):
        self.db.execute("INSERT OR IGNORE INTO sources VALUES(?,?)", (key, source))

        if url:
            self.db.execute(
                "INSERT OR IGNORE INTO source_links VALUES(?,?,?)", (key, source, url)
            )

    def lead(self, key, url, details, source):
        existing = self.db.execute(
            "SELECT id,details,state FROM inbox WHERE url=? AND source=?", (url, source)
        ).fetchone()
        if existing:
            if (
                details
                and details != existing["details"]
                and existing["state"] in ("new", "review")
            ):
                self.db.execute(
                    "UPDATE inbox SET details=?,state='new' WHERE id=?",
                    (details, existing["id"]),
                )
                return True
            return False
        return self.db.execute(
            "INSERT OR IGNORE INTO inbox(id,url,details,source) VALUES(?,?,?,?)",
            (key, url, details, source),
        ).rowcount

    def state(self, key, state, score=0, preview=None):
        self.db.execute(
            "UPDATE jobs SET state=?,score=?,preview=? WHERE id=?",
            (state, score, json.dumps(preview or {}), key),
        )

    def emit(self, kind, subject, payload):
        self.db.execute(
            "INSERT INTO outbox(kind,subject,payload) VALUES(?,?,?)",
            (kind, subject, json.dumps(payload)),
        )

    def block(self, key, body):
        active = self.db.execute(
            "SELECT body FROM issues WHERE id=? AND closed=0", (key,)
        ).fetchone()
        if active and json.loads(active[0]) == body:
            return
        self.db.execute(
            "INSERT OR REPLACE INTO issues VALUES(?,?,?,?,0)",
            (key, key, json.dumps(body), time.time()),
        )
        self.emit("issue", key, body)
        self.emit("discord", key, body)

    def reserve(self, j):
        with self.transaction():
            if not self.get("live", False):
                return False
            if self.db.execute(
                "SELECT 1 FROM attempts WHERE job=? AND state!='released'", (j.key,)
            ).fetchone():
                return False
            day = datetime.now().astimezone().date().isoformat()
            count = self.db.execute(
                "SELECT count(*) FROM attempts WHERE day=? AND state!='released'",
                (day,),
            ).fetchone()[0]
            previous = self.db.execute(
                "SELECT 1 FROM attempts WHERE state!='released' LIMIT 1"
            ).fetchone()
            if count >= 5 or (
                previous and not self.get("first_receipt_verified", False)
            ):
                return False
            self.db.execute(
                "INSERT INTO attempts(job,day,state,started) VALUES(?,?,'pending',?)",
                (j.key, day, time.time()),
            )
            self.state(j.key, "pending")
            return True

    def confirm(self, j, evidence):
        with self.transaction():
            changed = self.db.execute(
                "UPDATE attempts SET state='confirmed',evidence=? WHERE job=? AND state='pending'",
                (evidence, j.key),
            ).rowcount
            if changed:
                self.state(j.key, "confirmed")
                if self.db.execute(
                    "UPDATE issues SET closed=1 WHERE id=? AND closed=0", (j.key,)
                ).rowcount:
                    self.emit("close", j.key, {})
                self.emit(
                    "applied",
                    j.key,
                    {
                        "job": j.data(),
                        "evidence": evidence,
                        "date": datetime.now().astimezone().date().isoformat(),
                    },
                )

    def backup(self, dest):
        with sqlite3.connect(dest) as target:
            self.db.backup(target)
