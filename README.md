# Sus Link

Sus Link is a Discord bot that helps you investigate suspicious links without opening them on your own device. Right-click a message to inspect its links in an isolated Instabox cloud browser, check for phishing patterns, deceptive forms, unexpected redirects, and attempted downloads, and receive a private threat report with a risk score, screenshots, and an AI-powered assessment from Gemini.

## Free-tier setup

Sus Link is designed to work with the providers' free tiers:

- **Instabox provides one machine on its Free plan.** Sus Link creates and reuses that single machine, resuming it when paused instead of creating a new machine for every scan. See [Instabox's current plan limits](https://instabox.sh/docs/limits).
- **The Gemini API offers a free tier** with free input and output tokens for supported models, subject to model availability and project rate limits. Create your API key in [Google AI Studio](https://aistudio.google.com/) and check your project's free-tier quotas. See [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

Stay within each provider's free-tier limits to use these services without paid API usage. The bot itself still needs a computer or hosting service to run on; provider plans and quotas can change.

## Run

Requires Python 3.11 or newer (the supplied environment uses Python 3.14).

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

Create `.env` using `.env.example` as a reference. Keep your existing Discord token and fill in `INSTABOX_API` and `GEMINI_API`. Do not share these keys in chat or commit `.env`. No owner ID setting is needed: Discord's `Bot.is_owner()` discovers the application owner. For team-owned applications discord.py also recognizes team developers and admins as owners.

Invite the Discord application using the `bot` and `applications.commands` scopes. No Administrator permission is needed. Message Content Intent can stay **disabled** in the Developer Portal. Sus Link receives the selected message through the context-command interaction; it does not monitor channel messages.

```sh
venv/bin/python main.py
```

**Commands never sync automatically at startup.** After starting the bot, the bot owner must open a DM with the bot and send:

```text
!sync
```

This owner-only command manually syncs the global application commands. No owner ID configuration is needed. Message Content Intent can remain **disabled**: Discord supplies DM content, and the selected message for a message context command, without that intent. Discord may take time to display a newly synced global command.

Once synced, right-click a message containing an HTTP(S) link, then choose **Apps → Sus Link Checker**. For multiple links, choose one from the private selector. Run `!sync` manually again after adding or changing application commands; ordinary restarts do not need a sync.

The original advanced sync options are also available: `!sync <guild_id> ...` syncs the specified guilds. In a server, `!sync ~` syncs that guild, `!sync *` copies global commands to that guild and syncs, and `!sync ^` removes that guild's commands. Reading ordinary `!` commands in server messages requires Message Content Intent; use DM `!sync` to keep the intent disabled. The DM sync confirmation is a normal private DM message; scan interactions remain ephemeral Components V2 replies.

The first scan provisions a dedicated `sus-link` machine and installs Playwright/Chromium inside it; this can take several minutes. Do not use this dedicated machine for other work. An existing machine with the same name but without Sus Link's application label is rejected. Subsequent scans reuse it, resuming paused machines or starting stopped machines and waiting for readiness. The service does not delete machines or change the provider's idle-pause policy.

## What it shows

- One private checklist: ✅ completed stages and ⏳ running/pending stages. Edits coalesce and are spaced at least five seconds apart; discord.py handles Discord's API rate-limit responses.
- Verdict, observed-signal risk score, AI confidence, recommendation, final destination, and scan timestamp.
- Buttons for evidence, screenshot, full JSON report, and rescan. Every button checks bot ownership. Buttons expire after ten minutes; run the command again afterward.
- One scan at a time. Start a single bot process against the database; multiple replicas are not supported in this version.

The numeric score is a transparent sum of observed signals, capped at 100. The full report lists each signal's points. It is not a calibrated probability. Gemini's visual/text assessment can raise the verdict without changing the observed-signal score. Failed navigation, detected access challenges, or unavailable AI produce an **Inconclusive** verdict, with evidence retained where available.

## Isolation and coverage

A fresh, nonpersistent Chromium context runs inside the Instabox VM for each scan, with Chromium's sandbox enabled. The bot host never visits the suspect URL. Browser HTTP(S) requests pass through a proxy that resolves and validates destination IPs and connects to the validated numeric address. Local, private, reserved, and multicast destinations are blocked, including browser subrequests and redirects. Only HTTP port 80 and HTTPS port 443 are supported. WebSockets, service workers, non-GET/HEAD browser requests, downloads, dialogs, and popups are blocked or canceled.

The collector observes a single anonymous page for roughly four seconds after initial loading. It records navigation responses, bounded request metadata, forms, visible text, attempted downloads, and a viewport screenshot. It does not sign in, submit forms, execute downloaded files, inspect every embedded frame, or exhaustively crawl the website. Sites requiring login, CAPTCHA, POST requests, or WebSockets may not work normally. These controls defend against ordinary malicious page behavior; they do not guarantee containment of a browser or VM exploit. The Gemini model receives untrusted page evidence as data and has no tools or credentials.

URL query strings are redacted in stored URL metadata and reports, but the real URL must be sent to Instabox to visit it. Page text, screenshots, paths, or Instabox command history can still contain sensitive information. Gemini receives collected page evidence and a screenshot. Discord receives the private report and any requested screenshot/download. Ephemeral messages are not end-to-end encryption.

SQLite stores machine identity, model budgets/cooldowns, and scan evidence/reports in `database/db.sqlite3` by default. The `database/` folder is created automatically and excluded from Git, including SQLite journal files. If upgrading from the old root-level `db.sqlite3`, stop the running bot before restarting: startup moves the existing database and its SQLite sidecar files into `database/`. Migration refuses to move a database that is still open and never overwrites an existing destination database. Screenshots remain in memory for the report buttons rather than being written to the local database. Scan records currently have no automatic retention cleanup. No Discord message body, user record, or API key is saved in the scan tables.

## Gemini fallback

Default preference: `gemini-3.8-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`.

`GEMINI_DAILY_BUDGETS=20,20,500` sets local request budgets, not a guarantee of Google's quota. Verify actual project limits in Google AI Studio. A standard scan uses one successful analysis request, with additional attempts only for fallback. Requests are reserved in the database before sending; ambiguous failures count conservatively. Usage by other apps in the same Google project is unknown to this bot.

Daily exhaustion and local daily budgets retry after midnight in `America/Los_Angeles`, including daylight saving changes. Minute/token limits use Google's retry delay when provided, or a short cooldown when identifiable. Unclassified quota errors use a 24-hour cooldown. The highest-priority eligible model is selected again on each scan. If every model is unavailable, observed evidence is still returned with an inconclusive verdict.

## Validation

```sh
venv/bin/python -m unittest discover -s tests -v
```

Tests exercise URL handling, blocked addresses, risk rules, quota reset timing, persistent model fallback, machine creation/resume and failed operations, owner checks, progress throttling, and Components V2 serialization. They mock external services and do not spend API quota. A live Discord → Instabox → Gemini scan still needs real provider keys.

API references: [Instabox](https://instabox.sh/docs/api), [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Gemini quotas](https://ai.google.dev/gemini-api/docs/rate-limits), [Discord context-command message access](https://docs.discord.com/developers/events/gateway#message-content-intent).
