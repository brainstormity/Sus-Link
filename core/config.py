from __future__ import annotations
import os
from pathlib import Path
from typing import Final
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: Final[str] = os.getenv("BOT_TOKEN", "")
PROJECT_DIR: Final[Path] = Path(__file__).resolve().parents[1]
DATABASE_DIR: Final[Path] = PROJECT_DIR / "database"
_db_url = os.getenv("DB_URL", "")
# Keep the old default compatible while moving its files into database/.
if not _db_url or _db_url in ("sqlite://db.sqlite3", "sqlite://database/db.sqlite3"):
    _db_url = f"sqlite://{DATABASE_DIR / 'db.sqlite3'}"
DB_URL: Final[str] = _db_url

INSTABOX_API: Final[str] = os.getenv("INSTABOX_API", "")
GEMINI_API: Final[str] = os.getenv("GEMINI_API", "")

# Owner identity is discovered by discord.py's Bot.is_owner().
INSTABOX_MACHINE_NAME: Final[str] = os.getenv("INSTABOX_MACHINE_NAME", "sus-link")
GEMINI_MODELS: Final[tuple[str, ...]] = tuple(
    x.strip()
    for x in os.getenv("GEMINI_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite").split(
        ","
    )
    if x.strip()
)
GEMINI_DAILY_BUDGETS: Final[tuple[int, ...]] = tuple(
    int(x) for x in os.getenv("GEMINI_DAILY_BUDGETS", "20,500").split(",")
)
