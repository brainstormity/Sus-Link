# Install and run Sus Link

[Back to README](../README.md) · First: [Discord bot setup](discord-setup.md)

## 1. Install dependencies

Install Python 3.11 or newer, then run these commands from the project folder:

```sh
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
```

On Windows, use `venv\Scripts\python.exe` instead of `venv/bin/python`.

## 2. Add your API keys

Create `.env` from [.env.example](../.env.example), keeping any existing values. Fill in:

| Setting | Where to get it |
| --- | --- |
| `BOT_TOKEN` | Discord Developer Portal → your app → Bot |
| `INSTABOX_API` | [Instabox](https://instabox.sh) → API keys |
| `GEMINI_API` | [Google AI Studio](https://aistudio.google.com/) → API key |

Keep `.env` private. It is excluded from Git. No owner ID configuration is required.

Instabox provides **one machine on its Free plan**; Sus Link creates and reuses that machine. Gemini offers a **free API tier** for supported models. Stay within the providers' free-tier limits; plans and quotas can change. Your computer or hosting service still needs to run the bot.

## 3. Start and sync

```sh
venv/bin/python main.py
```

Keep the bot running. Open its Discord DM and send `!sync` to register the command manually. See [Discord setup](discord-setup.md) for the required **User Install** settings.

The first scan creates the isolated machine and installs its browser. This may take several minutes. Later scans reuse it, resuming paused machines or starting stopped machines. Keep this dedicated machine for Sus Link only.

## Optional settings

The defaults are suitable for getting started:

| Setting | Default | Purpose |
| --- | --- | --- |
| `DB_URL` | `sqlite://database/db.sqlite3` | Local scan history and provider state |
| `INSTABOX_MACHINE_NAME` | `sus-link` | Dedicated machine name |
| `GEMINI_MODELS` | `gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash-lite` | Model preference order |
| `GEMINI_DAILY_BUDGETS` | `20,20,500` | Local request budgets in the same order |
| `PROGRESS_EDIT_SECONDS` | `5` | Minimum time between checklist edits |

Local budgets do not guarantee Google's quotas. Check your actual project limits in AI Studio. Run only one bot process against this database.

The `database/` folder is created automatically and excluded from Git. When upgrading from the old root-level database, **stop the bot before restarting**. Startup moves the existing database into `database/` without overwriting another database. If automatic open-file verification is unavailable, stop the bot and move `db.sqlite3` and any `-wal`, `-shm`, or `-journal` sidecar files into `database/` yourself.

Next: [Use Sus Link](usage.md). For privacy, coverage, and quota behavior, see [technical details](technical-details.md).
