# Technical details

[Back to README](../README.md)

## Isolation, coverage, and storage


A fresh, nonpersistent Chromium context runs inside the Instabox VM for each scan, with Chromium's sandbox enabled. The bot host never visits the suspect URL. Browser HTTP(S) requests pass through a proxy that resolves and validates destination IPs and connects to the validated numeric address. Local, private, reserved, and multicast destinations are blocked, including browser subrequests and redirects. Only HTTP port 80 and HTTPS port 443 are supported. WebSockets, service workers, non-GET/HEAD browser requests, downloads, dialogs, and popups are blocked or canceled.

The collector waits 4–12 seconds for readable, stable content on a single anonymous page. It gives transient challenges time to clear naturally and retries failed navigation or HTTP 5xx once; 404 pages are not retried. It can recover content already rendered when navigation times out, and retains text evidence when screenshot capture fails. It records navigation responses, bounded request metadata, forms, visible text, attempted downloads, and a viewport screenshot. It does not sign in, submit forms, execute downloaded files, inspect every embedded frame, or exhaustively crawl the website. Sites requiring login, CAPTCHA, POST requests, or WebSockets may not work normally. These controls defend against ordinary malicious page behavior; they do not guarantee containment of a browser or VM exploit. The Gemini model receives untrusted page evidence as data and has no tools or credentials.

URL query strings are redacted in stored URL metadata and reports, but the real URL must be sent to Instabox to visit it. Page text, screenshots, paths, or Instabox command history can still contain sensitive information. Gemini receives collected page evidence and a screenshot. Discord receives the private report and its screenshot. Ephemeral messages are not end-to-end encryption.

SQLite stores machine identity, model budgets/cooldowns, and scan evidence/reports in `database/db.sqlite3` by default. The `database/` folder is created automatically and excluded from Git, including SQLite journal files. If upgrading from the old root-level `db.sqlite3`, stop the running bot before restarting: startup moves the existing database and its SQLite sidecar files into `database/`. Migration refuses to move a database that is still open and never overwrites an existing destination database. Screenshots are attached directly to the private Discord report rather than being written to the local database. Scan records currently have no automatic retention cleanup. No Discord message body, user record, or API key is saved in the scan tables.

## Assessment quality

Reports list specific inspection limits: missing pages, denied access, bot challenges, empty content, or unavailable AI. A failed check is not a clean bill of health. Concrete warning evidence remains visible even when coverage is incomplete. A readable page without detected threats can receive Low risk with appropriately limited confidence; this is not a guarantee of safety. Missing domain ownership or reputation data alone does not force an inconclusive result. Gemini has an 8,192-token output allowance to reduce truncated structured responses.

## Gemini fallback and quotas


Default preference: `gemini-3.8-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`.

`GEMINI_DAILY_BUDGETS=20,20,500` sets local request budgets, not a guarantee of Google's quota. Verify actual project limits in Google AI Studio. A standard scan uses one successful analysis request. A temporary server error gets one retry on the same model. Lower models are used for quota cooldowns, local daily budgets, or HTTP 503 high-demand/unavailable responses that persist after one retry. High demand does not impose a quota cooldown: the top eligible model is tried first again on the next scan. Connection failures, timeouts, invalid reports, and other model-specific HTTP failures also try the next eligible model without a quota cooldown. Authentication/permission errors stop the chain so the API credentials can be checked. If all eligible models fail, the report is inconclusive. Failure reasons are logged and retained with the assessment. Model-selection reasons are retained with the assessment. The Evidence interface is currently hidden from reports. Requests are reserved in the database before sending; ambiguous failures count conservatively. Usage by other apps in the same Google project is unknown to this bot.

Daily exhaustion and local daily budgets retry after midnight in `America/Los_Angeles`, including daylight saving changes. Minute/token limits use Google's retry delay when provided, or a short cooldown when identifiable. Unclassified quota errors use a 24-hour cooldown. The highest-priority eligible model is selected again on each scan. If every model is unavailable, observed evidence is still returned. Concrete warning signals can still support a Suspicious or High risk verdict; absence of detected warnings cannot establish Low risk without AI analysis.

## Tests


```sh
venv/bin/python -m unittest discover -s tests -v
```

Tests exercise URL handling, blocked addresses, risk rules, quota reset timing, persistent model fallback, machine creation/resume and failed operations, owner checks, DM report delivery, and Components V2 serialization. They mock external services and do not spend API quota. A live Discord → Instabox → Gemini scan still needs real provider keys.

API references: [Instabox](https://instabox.sh/docs/api), [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Gemini quotas](https://ai.google.dev/gemini-api/docs/rate-limits), [Discord context-command message access](https://docs.discord.com/developers/events/gateway#message-content-intent).
