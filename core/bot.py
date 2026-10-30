from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from tortoise import Tortoise

from . import config

log = logging.getLogger("Bot")
__all__ = ("Bot",)


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Activity(
                name="Built by @brainstormity", type=discord.ActivityType.streaming
            ),
        )
        self.http_session = None

    async def setup_hook(self):
        from services.scanner import Scanner

        from .database import prepare_database

        prepare_database()
        await Tortoise.init(
            db_url=config.DB_URL, modules={"models": ["core.models"]}, use_tz=True
        )
        await Tortoise.generate_schemas(safe=True)
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=300)
        )
        self.scanner = Scanner(self.http_session)
        for file in sorted((Path(__file__).resolve().parents[1] / "cogs").glob("*.py")):
            if not file.name.startswith("_"):
                await self.load_extension(f"cogs.{file.stem}")

    async def close(self):
        try:
            await super().close()
        finally:
            if self.http_session:
                await self.http_session.close()
            await Tortoise.close_connections()
