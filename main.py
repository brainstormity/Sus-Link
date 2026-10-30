from __future__ import annotations

import asyncio
import typing

import discord
from discord.ext import commands

from discord import utils
from core import Bot, config

bot = Bot()

@bot.command()
@commands.is_owner()
async def sync(
    ctx: commands.Context,
    guilds: commands.Greedy[discord.Object],
    spec: typing.Optional[typing.Literal["~", "*", "^"]] = None,
) -> None:
    if not guilds:
        if spec is not None and ctx.guild is None:
            await ctx.send(
                "Guild sync options must be used in a server. Send !sync in DM to sync globally."
            )
            return
        if spec == "~":
            synced_commands = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced_commands = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced_commands = []
        else:
            synced_commands = await ctx.bot.tree.sync()
        await ctx.send(
            f"Synced {len(synced_commands)} commands "
            f"{'globally' if spec is None else 'to the current guild.'}"
        )
        return

    successful = 0
    for guild in guilds:
        try:
            await ctx.bot.tree.sync(guild=guild)
        except discord.HTTPException:
            pass
        else:
            successful += 1
    await ctx.send(f"Synced the tree to {successful}/{len(guilds)}.")


async def main():
    utils.setup_logging()
    if not config.BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN in .env before starting Sus Link.")
    async with bot:
        await bot.start(config.BOT_TOKEN, reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
