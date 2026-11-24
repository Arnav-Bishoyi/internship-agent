import argparse
import fcntl
import getpass
import hashlib
import json
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import keyring
import requests
import yaml

from .integrations.discord import gateway
from .integrations.google import SERVICE, authorize
from .store import Store
from .worker import Worker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / ".private"


def initialize(home):
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("profile", "answers", "employers", "matching"):
        src = name + (".example" if name in {"profile", "answers"} else "") + ".yaml"
        target = home / (name + ".yaml")
        if not target.exists():
            shutil.copyfile(ROOT / "config" / src, target)
    if not (home / "settings.yaml").exists():
        (home / "settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "spreadsheet": "",
                    "tab": "Untitled",
                    "discord": {"guild": "", "channel": "", "user": ""},
                }
            )
        )
    s = Store(home / "agent.sqlite")
    if s.get("live") is None:
        s.set("live", False)
    s.db.close()


def config(home):
    def read(name):
        return yaml.safe_load((home / (name + ".yaml")).read_text()) or {}

    return (
        read("settings")
        | read("employers")
        | read("matching")
        | {"profile": read("profile"), "answers": read("answers")}
    )


@contextmanager
def locked(home):
    with (home / "worker.lock").open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("The worker already holds this state directory.")
        yield


def health(w, token):
    def google():
        w.gmail().api.list(
            userId="me",
            maxResults=1,
            q="newer_than:1d from:jobalerts-noreply@linkedin.com",
        ).execute()

    def sheets():
        w.sheets().rows()
        w.sheets().ensure_actions()

    def discord():
        if not token or not all(w.c["discord"].values()):
            raise ValueError("configure-discord required")
        auth = {"Authorization": "Bot " + token}
        channel = requests.get(
            f"https://discord.com/api/v10/channels/{w.c['discord']['channel']}",
            headers=auth,
            timeout=10,
        )
        channel.raise_for_status()
        if str(channel.json().get("guild_id")) != str(w.c["discord"]["guild"]):
            raise ValueError("Discord guild mismatch")

    def docs():
        from .profile import pdf

        for k in ("resume_2028", "resume_2029", "transcript"):
            pdf(w.c["profile"], k)

    def forms():
        if not w.c["forms"]:
            raise ValueError("Configure a permitted employer form")

    def answers():
        if not w.c["answers"].get("email") or not w.c["profile"].get("evidence"):
            raise ValueError("Complete the local applicant profile")

    result = {}
    diagnostics = {
        "gmail": "Connect Google OAuth",
        "tracker": "Connect Google OAuth and check tracker access",
        "discord": "Configure a Discord bot and channel",
        "documents": "Check the private PDF paths",
        "forms": "Configure a verified permitted employer form",
        "profile": "Complete the private profile and answers",
    }
    for label, fn in {
        "gmail": google,
        "tracker": sheets,
        "discord": discord,
        "documents": docs,
        "forms": forms,
        "profile": answers,
    }.items():
        try:
            fn()
        except Exception as e:
            result[label] = diagnostics[label] + " (" + type(e).__name__ + ")"
        else:
            result[label] = "ok"
    return result


def previews(s):
    return [
        dict(
            id=r[0],
            score=r[1],
            job={
                k: v
                for k, v in json.loads(r[2]).items()
                if k in {"company", "title", "url", "req"}
            },
            preview=json.loads(r[3]),
        )
        for r in s.db.execute(
            "SELECT id,score,data,preview FROM jobs WHERE state='ready' ORDER BY score DESC,id LIMIT 5"
        )
    ]


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def install(home):
    if sys.platform != "darwin":
        raise SystemExit("launchd installation requires macOS.")
    label = "com.local.internship-agent"
    dest = Path.home() / "Library" / "LaunchAgents" / (label + ".plist")
    dest.parent.mkdir(parents=True, exist_ok=True)
    previous = dest.read_bytes() if dest.exists() else b""
    dest.write_bytes(
        plistlib.dumps(
            {
                "Label": label,
                "ProgramArguments": [
                    sys.executable,
                    "-m",
                    "internship_agent.cli",
                    "--state",
                    str(home),
                    "run",
                ],
                "WorkingDirectory": str(ROOT),
                "KeepAlive": True,
                "RunAtLoad": True,
                "ThrottleInterval": 30,
                "StandardOutPath": str(home / "worker.log"),
                "StandardErrorPath": str(home / "worker.log"),
                "Umask": 63,
            }
        )
    )
    target = f"gui/{os.getuid()}"
    if (
        subprocess.run(
            ["launchctl", "print", target + "/" + label], capture_output=True
        ).returncode
        == 0
    ):
        if previous == dest.read_bytes():
            subprocess.run(
                ["launchctl", "kickstart", "-k", target + "/" + label], check=True
            )
            print("Reloaded", label)
            return
        subprocess.run(["launchctl", "bootout", target + "/" + label], check=True)
        for _ in range(40):
            if subprocess.run(
                ["launchctl", "print", target + "/" + label], capture_output=True
            ).returncode:
                break
            time.sleep(0.25)
    subprocess.run(["launchctl", "bootstrap", target, str(dest)], check=True)
    print("Installed and started", label)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT)
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in (
        "setup",
        "doctor",
        "preview",
        "enable",
        "pause",
        "status",
        "verify-first",
        "reconcile",
        "once",
        "run",
        "install",
        "configure-discord",
    ):
        sub.add_parser(cmd)
    p = sub.add_parser("authorize-google")
    p.add_argument("client_json", type=Path)
    opts = parser.parse_args()
    home = opts.state.expanduser().resolve()
    cmd = opts.command
    if cmd == "setup":
        initialize(home)
        print("Private configuration:", home)
        return
    if not (home / "settings.yaml").is_file():
        raise SystemExit("Run setup first.")
    if cmd == "authorize-google":
        authorize(str(opts.client_json))
        print("Google consent stored in Keychain.")
        return
    if cmd == "configure-discord":
        settings = yaml.safe_load((home / "settings.yaml").read_text())
        ids = {
            k: input(f"Discord {k} ID: ").strip() for k in ("guild", "channel", "user")
        }
        if not all(v.isdecimal() for v in ids.values()):
            raise SystemExit("Expected numeric Discord IDs.")
        token = getpass.getpass("Bot token: ").strip()
        if not token:
            raise SystemExit("A bot token is required.")
        keyring.set_password(SERVICE, "discord", token)
        settings["discord"] = ids
        (home / "settings.yaml").write_text(yaml.safe_dump(settings))
        return
    if cmd == "install":
        install(home)
        return
    s = Store(home / "agent.sqlite")
    w = Worker(s, config(home))
    if cmd == "pause":
        s.set("live", False)
        return
    if cmd == "status":
        print(
            json.dumps(
                {
                    "live": s.get("live", False),
                    "trial_start": s.get("trial_start"),
                    "heartbeat": s.get("heartbeat"),
                    "jobs": dict(
                        s.db.execute("SELECT state,count(*) FROM jobs GROUP BY state")
                    ),
                    "pending_deliveries": s.db.execute(
                        "SELECT count(*) FROM outbox WHERE done=0"
                    ).fetchone()[0],
                    "errors": dict(
                        s.db.execute(
                            "SELECT k,v FROM settings WHERE k LIKE 'error:%' AND v!='null'"
                        )
                    ),
                },
                indent=2,
            )
        )
        return
    if cmd == "preview":
        rows = previews(s)
        print(json.dumps(rows, indent=2))
        if len(rows) == 5:
            s.set("preview_seen", fingerprint(rows))
        return
    if cmd == "verify-first":
        first = s.db.execute(
            "SELECT job,state,evidence FROM attempts WHERE state!='released' ORDER BY id LIMIT 1"
        ).fetchone()
        if not first or first[1] != "confirmed":
            raise SystemExit("First live receipt is pending.")
        synced = s.db.execute(
            "SELECT 1 FROM outbox WHERE subject=? AND kind='applied' AND done=1",
            (first[0],),
        ).fetchone()
        if not synced:
            raise SystemExit("First tracker write is pending.")
        print("First attempt:", first[0], first[2])
        if (
            input("After checking the receipt and tracker, enter VERIFIED: ")
            == "VERIFIED"
        ):
            s.set("first_receipt_verified", True)
        return
    token = (
        keyring.get_password(SERVICE, "discord")
        if all(w.c["discord"].values())
        else None
    )
    if cmd == "doctor":
        print(json.dumps(health(w, token), indent=2))
        return
    if cmd == "enable":
        rows = previews(s)
        if any(v != "ok" for v in health(w, token).values()):
            raise SystemExit("Complete doctor checks first.")
        if (
            time.time() - (s.get("trial_start") or time.time()) < 86400
            or len(rows) < 5
            or fingerprint(rows) != s.get("preview_seen")
        ):
            raise SystemExit(
                "Complete the connected 24-hour trial and review the current five previews."
            )
        if input("Enable five-per-day live submissions? Type ENABLE: ") == "ENABLE":
            s.set("live", True)
        return
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(message)s"
    )
    with locked(home):
        if cmd == "reconcile":
            w.reconcile()
            return
        thread = None
        last_health = 0
        while True:
            if token and cmd == "run" and (thread is None or not thread.is_alive()):
                thread = gateway(s.path, w.c["discord"], token)
            if time.time() - last_health > 600:
                last_health = time.time()
                ok = all(v == "ok" for v in health(w, token).values())
                if ok and (
                    not s.get("trial_start")
                    or time.time() - (s.get("heartbeat") or 0) > 600
                ):
                    s.set("trial_start", time.time())
                if not ok and not s.get("live"):
                    s.set("trial_start", None)
            w.tick(token)
            s.set("heartbeat", time.time())
            if cmd == "once":
                return
            time.sleep(15)


if __name__ == "__main__":
    main()
