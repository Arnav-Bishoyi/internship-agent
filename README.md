# Internship agent

A single-user Python worker for Summer 2027 US and India internships. It runs on an awake Mac, reads LinkedIn job alerts, discovers employer postings, accepts roles through a private Discord command, and checks the live Google Sheets tracker immediately before every submission.

## Start

From the cloned repository, using Python 3.11 or newer:

```sh
uv sync --locked
uv run playwright install chromium
uv run internship-agent setup
uv run internship-agent doctor
```

The default private state directory is `.private/` in the checkout. It holds your editable profile, PDF paths, employer definitions, SQLite database, logs, and backup. Google OAuth and Discord credentials use macOS Keychain. Keep private state on an encrypted local disk. Git ignores it. The default is discovery and preview mode.

[Setup, service operation, and recovery](docs/runbook.md)

## Operating behavior

- Employer feeds refresh every 30 minutes. The Gmail scan starts with ten days of history and repeats every twelve hours. Discord accepts `/role url:<link> details:<optional employer and title>`.
- Discovery merges matching leads, ranks fit against applicant evidence and reviews uncertain eligibility. Historical tracker entries can be sparse. Conflicting or unclear matches are sent to review.
- Employer-specific forms require an operator-reviewed definition. A synthetic example documents the exact labels, selectors, file types, submission destination, and receipt evidence. Fresh checkout coverage is public discovery and handoff. Each enabled form needs testing against its permitted channel.
- Every click is preceded by a durable reservation and a fresh tracker read. An uncertain click remains reserved until reconciled. An external manual submission in the instant between the Sheet read and the click cannot be made atomic with the employer site.
- Live mode requires a connected 24-hour trial, five current previews and your explicit enable command. The combined limit is five attempts per local calendar day. The first receipt and completed tracker write require your verification before subsequent submissions.

Run the full synthetic suite with `uv run python -m unittest discover -s tests -v`. The browser test hosts a disposable fixture on loopback, uploads synthetic PDF bytes, and checks the received body.
