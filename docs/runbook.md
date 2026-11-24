# Setup and operations

Run commands from the clone. The examples use `uv run internship-agent`; the installed `.venv/bin/internship-agent` works too. Run `setup` once. It reuses existing private configuration. Use `--state /absolute/private/directory` before a command if you need another state directory.

## Google and the tracker

1. In a Google Cloud project, enable Gmail API and Google Sheets API. Set up the OAuth consent screen and add your Google account as a test user when appropriate. Create a **Desktop app** OAuth client and download its JSON to a private directory. Google documents the process in its [Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python).
2. Run `uv run internship-agent authorize-google /absolute/path/to/client.json`. Complete the local browser consent on the Google account that receives LinkedIn alerts and can edit your tracker. The worker requests Gmail read-only and Sheets access. It stores the offline credential in Keychain. For sustained operation, account for Google's seven-day refresh-token limit on external apps in Testing with these scopes. Configure a publishing status suitable for the account and reauthorize as needed. [Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
3. Set the spreadsheet ID and tab name in `.private/settings.yaml`. The configured application tab expects the eleven existing columns from Company through Notes / Source. The worker checks the header on each read. The separate Needs Action tab is initialized by doctor when necessary.
4. In LinkedIn Jobs, save daily **email** alerts covering both countries and the target role families. Check which email address your account uses. A matching email digest supplies job links and context. Do not put social account passwords into the agent. [LinkedIn job alerts](https://www.linkedin.com/help/linkedin/answer/a511279/)
5. If OAuth expires during operation, re-run authorization. Restart the worker after changing configuration or credentials.

## Discord

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications). Install it to your own server with the bot and applications.commands scopes. Give the bot View Channel and Send Messages in your private application channel. It uses slash-command interactions through an outbound Gateway connection. The privileged Message Content intent is unnecessary.
2. Enable Discord Developer Mode and copy your server, channel and user IDs. Run `uv run internship-agent configure-discord` in a terminal. Enter the three IDs and enter the bot token at the hidden prompt.
3. Start the worker. Use `/role` in the configured channel. For campus-only or sign-in-only roles, include the exact employer and title. Acknowledgment means the role is saved locally. The worker attempts to match it to its configured employer boards.

## Profile and permitted employer forms

- Edit `.private/profile.yaml` and `.private/answers.yaml`. Verify PDF paths, skills evidence, email, availability, and actual authorization answers. Set `may_2029_accurate` only if the later academic plan is accurate. Omit answers that need individual judgment. Declare the exact form values for country-specific eligibility questions.
- Manage employer feeds in `.private/employers.yaml`. Greenhouse and Lever entries use a verified company slug. A careers entry has a list of employer-owned `urls` that publish JobPosting JSON-LD. The initial sources cover selected employers, not the whole market. Multi-source resolution requires an unambiguous employer posting; add boards to extend coverage.
- Add each permitted form under `forms` in the same private file. Start with `config/form.example.yaml`. Record the employer's permission reference. Bind the exact host, identity element, job path, all field labels and selectors, final submission path, and receipt. The form adapter supports native HTML controls including text, selects, checkboxes, and PDF attachments. It checks the complete control inventory and fails closed on changes. Use a review queue for opaque multi-step widgets.
- Use the special field answer `resume` for selected résumé uploads, `graduation_year` for matching form answers, and `transcript` with `accepts_unofficial: true` for an explicitly requested unofficial transcript. Confirm the selected attachment in preview.
- For a post-submit email challenge, define `verification` with `challenge` (selector), `kind` (code or link), `sender`, and `subject` (full-match regex). The message must also identify the current requisition, or contain the session reference read from a configured `binding_selector`. For codes include `pattern`, `input`, `continue`, and the approved POST `continue_path`. For links include `hosts` and an exact `path` regex. Allowed hosts and write paths must also be in the reviewed form policy. Provide an `email_receipt` with sender, subject and success-pattern regexes to reconcile after a restart. Receipts must identify the opening. Configure distinct, employer-specific templates and test with synthetic messages.
- The agent opens a clean browser session per form. Sites requiring an interactive account, redirects outside the reviewed flow, user attestations, unsupported questions, or challenges go to Needs Action. The exact URL and a manual next step are retained.

## Service and launch

```sh
uv run internship-agent doctor
uv run internship-agent install
uv run internship-agent status
uv run internship-agent preview
```

Install creates a LaunchAgent under the logged-in user's Library and starts it. The Mac must stay powered, awake, online, and logged in. Allow the relevant Keychain access if macOS prompts. Repeat install after changing private settings to reload the worker. It continues public-board discovery with unconfigured integrations. Doctor reports each missing component. The connected trial starts when the required components pass health checks.

After 24 connected hours, review all five printed previews locally. Use `enable` and type ENABLE to authorize unattended submissions. After the first employer receipt and tracker update, inspect both and use `verify-first`. Use `pause` to stop further live submissions. Pause does not recall one already in flight. Use `launchctl bootout gui/$(id -u)/com.local.internship-agent` to stop the service. Use install to start it again.

## Failures and recovery

- Needs Action contains the reason, original link, deadline when known, and possible-submission flag. Set Decision to `Applied manually`, `Resolved — resume`, or `Skip`. For an unresolved social link applied manually, first add the application to the main tracker with its source link in Notes / Source.
- For an uncertain click, check the employer confirmation and your email before deciding. The worker also searches for a correctly bound receipt when an employer receipt rule exists. A generic resume instruction does not repeat an uncertain submission. Mark Applied manually when confirmed or Skip to close. Stop the service before running the standalone reconcile command.
- A tracker outage defers all submissions. Google and Discord deliveries are retried from SQLite. Local application attempts and live Sheet evidence both protect against duplicate submits. Discord may redeliver after a prolonged ambiguous network failure beyond its nonce-deduplication window.
- A daily SQLite backup lives beside the database. For disaster recovery, pause and stop the service, preserve the existing private directory, then restore the backup to a fresh private state directory. Start in paused mode and reconcile with receipts and the live Sheet before enabling. Earlier backups can predate a click.
- The private worker log records subsystem and error class. Job URLs, answers, mail bodies, verification secrets and document bytes do not belong in support messages. The status command reports discovery and queue health.
