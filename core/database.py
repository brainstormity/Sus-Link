"""Prepare the local database directory and preserve the template's old database."""

from pathlib import Path
import shutil
import subprocess

from . import config


def prepare_database() -> None:
    config.DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    destination = config.DATABASE_DIR / "db.sqlite3"
    # External database URLs and explicitly customized locations stay untouched.
    if config.DB_URL != f"sqlite://{destination}":
        return
    legacy = config.PROJECT_DIR / "db.sqlite3"
    if not legacy.exists() or destination.exists():
        return
    # Moving SQLite files while another process has them open can corrupt data.
    # lsof is available on macOS; fail safely if this migration cannot be checked.
    try:
        result = subprocess.run(
            ["lsof", "-t", str(legacy)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "Stop the bot, then move db.sqlite3 and any db.sqlite3-wal/-shm/-journal "
            "files into database/ before restarting; open-file verification is unavailable."
        ) from exc
    if result.stdout.strip() or result.returncode != 1:
        raise RuntimeError(
            "The old db.sqlite3 is still open or could not be checked. Stop the running "
            "bot before restarting so it can be moved safely into database/."
        )
    sources = [
        Path(str(legacy) + suffix) for suffix in ("", "-wal", "-shm", "-journal")
    ]
    # Refuse partial migration leftovers rather than mixing two databases.
    if any((config.DATABASE_DIR / source.name).exists() for source in sources):
        raise RuntimeError(
            "Database migration found existing destination files; no files were moved."
        )
    for source in sources:
        if source.exists():
            shutil.move(str(source), str(config.DATABASE_DIR / source.name))
