from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import time
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from core import config
from core.reply import ReplyView
from services.urls import extract_urls, redact_url

log = logging.getLogger(__name__)
STAGES = (
    "Prepare isolated browser",
    "Inspect website and capture evidence",
    "Analyze threats with Gemini",
    "Build report",
)
COLORS = {
    "High risk": 0xED4245,
    "Suspicious": 0xFEE75C,
    "Low risk": 0x57F287,
    "Inconclusive": 0x99AAB5,
}


def display(value, limit=1500):
    # Defang destinations and escape user/page/model Markdown and mentions.
    value = str(value).replace("://", "[:]//")
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))[:limit]


class OwnerView(ReplyView):
    def __init__(self, bot, *args, **kwargs):
        self.bot = bot
        super().__init__(*args, timeout=600, **kwargs)

    async def interaction_check(self, interaction):
        if await self.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message(
            view=ReplyView("Only the bot owner can use Sus Link."), ephemeral=True
        )
        return False

    async def on_error(self, interaction, error, item):
        log.error("Sus Link component failed (%s)", type(error).__name__)
        view = ReplyView("This action failed. Please run Sus Link Checker again.")
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)


class Progress:
    def __init__(self, interaction):
        self.interaction = interaction
        self.stage = 0
        self.changed = asyncio.Event()
        self.last_edit = 0.0
        self.task = None

    def view(self):
        lines = ["## Sus Link · Scanning", ""]
        for index, label in enumerate(STAGES):
            state = "✅" if index < self.stage else "⏳"
            suffix = " — running" if index == self.stage else ""
            lines.append(f"{state} {label}{suffix}")
        lines.extend(
            ["", "-# Inspection runs in Instabox. No credentials are entered."]
        )
        return ReplyView("\n".join(lines), accent_color=0x5865F2)

    async def start(self):
        await self.interaction.edit_original_response(view=self.view())
        self.last_edit = time.monotonic()
        self.task = asyncio.create_task(self.pump())

    def set(self, stage):
        self.stage = stage
        self.changed.set()

    async def spacing(self):
        await asyncio.sleep(
            max(0, self.last_edit + config.PROGRESS_EDIT_SECONDS - time.monotonic())
        )

    async def pump(self):
        while True:
            await self.changed.wait()
            await self.spacing()
            self.changed.clear()
            try:
                await self.interaction.edit_original_response(view=self.view())
            except discord.HTTPException:
                log.warning("Progress edit unavailable; scan continues.")
            self.last_edit = time.monotonic()

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, discord.HTTPException):
                await self.task
            self.task = None
        await self.spacing()


class ReportView(OwnerView):
    def __init__(self, bot, cog, scan, picture, url):
        self.scan, self.picture, self.url, self.cog = scan, picture, url, cog
        report, ai = scan.report, scan.report["ai"]
        checks = "\n".join("✅ " + stage for stage in STAGES)
        body = (
            f"## Sus Link · {report['verdict']}\n"
            f"**Observed-signal score:** {report['score']}/100\n"
            f"**AI assessment confidence:** {display(ai['confidence'], 40)}\n\n"
            f"{display(ai['summary'], 700)}\n\n"
            f"**Recommendation**\n{display(ai['recommendation'], 550)}"
        )
        super().__init__(
            bot, body, accent_color=COLORS[report["verdict"]], include_footer=False
        )
        findings = report["findings"][:4]
        self.add_separator().add_body(
            "**Observed evidence**\n"
            + (
                "\n".join(f"• {display(f['finding'], 200)}" for f in findings)
                if findings
                else "No scored warning signals were observed during this limited inspection."
            )
        )
        self.add_separator().add_body(
            f"**Final destination**\n{display(scan.evidence.get('final_url', ''), 350)}\n\n"
            f"{checks}\n\n-# Score is rule-based, not a probability or guarantee of safety. "
            f"Model: {display(scan.model or 'unavailable', 80)} · {scan.created_at:%Y-%m-%d %H:%M UTC}"
        )
        row = discord.ui.ActionRow()
        actions = [
            ("Evidence", self.evidence),
            ("Screenshot", self.screenshot),
            ("Full report", self.full_report),
            ("Rescan", self.rescan),
        ]
        for label, callback in actions:
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                disabled=label == "Screenshot" and not picture,
            )
            button.callback = callback
            row.add_item(button)
        self._container.add_item(row)
        self.add_footer()

    async def evidence(self, interaction):
        report, ai = self.scan.report, self.scan.report["ai"]
        redirects = self.scan.evidence.get("redirects", [])
        text = "**Navigation**\n" + (
            "\n".join(
                f"• HTTP {r['status']}: {display(r['url'], 220)}" for r in redirects[:8]
            )
            or "No navigation response captured."
        )
        text += "\n\n**AI interpretation**\n" + (
            "\n".join("• " + display(x, 280) for x in ai["findings"][:5])
            or "No additional AI findings."
        )
        text += "\n\n**Coverage and limitations**\n" + display(
            self.scan.evidence.get("coverage", ""), 400
        )
        limitations = ai["limitations"] + self.scan.evidence.get("errors", [])
        if self.scan.evidence.get("challenge"):
            limitations.append("A possible CAPTCHA or access challenge was detected.")
        text += "\n" + "\n".join("• " + display(x, 180) for x in limitations[:5])
        await interaction.response.send_message(
            view=ReplyView(text[:3900]), ephemeral=True
        )

    async def screenshot(self, interaction):
        view = ReplyView(
            "## Sus Link · Captured page\nUntrusted website content shown as an image."
        )
        view.add_header_image("attachment://sus-link.jpg")
        await interaction.response.send_message(
            view=view,
            file=discord.File(io.BytesIO(self.picture), filename="sus-link.jpg"),
            ephemeral=True,
        )

    async def full_report(self, interaction):
        data = {
            "scan_id": str(self.scan.id),
            "scanned_at": self.scan.created_at.isoformat(),
            "model": self.scan.model,
            "report": self.scan.report,
            "evidence": self.scan.evidence,
        }
        await interaction.response.send_message(
            view=ReplyView(
                "Full report and captured evidence. "
                "URLs may be untrusted; query strings have been redacted."
            ),
            file=discord.File(
                io.BytesIO(json.dumps(data, indent=2, ensure_ascii=False).encode()),
                filename="sus-link-report.json",
            ),
            ephemeral=True,
        )

    async def rescan(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.scan(interaction, self.url)


class LinkPicker(OwnerView):
    def __init__(self, bot, cog, urls):
        super().__init__(bot, "## Sus Link\nChoose a link to inspect.")
        self.cog, self.urls = cog, urls
        select = discord.ui.Select(
            placeholder="Select a link",
            options=[
                discord.SelectOption(
                    label=f"{index + 1}. {urlsplit(url).hostname}"[:100],
                    value=str(index),
                    description=redact_url(url)[:100],
                )
                for index, url in enumerate(urls)
            ],
        )
        select.callback = self.selected
        self.select = select
        self._container.add_item(discord.ui.ActionRow(select))

    async def selected(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.scan(interaction, self.urls[int(self.select.values[0])])


class SusLink(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.context_menu = app_commands.ContextMenu(
            name="Sus Link Checker", callback=self.check_message
        )
        bot.tree.add_command(self.context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.context_menu.name, type=self.context_menu.type
        )

    async def check_message(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        # Acknowledge immediately; owner discovery can require Discord's API.
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.edit_original_response(
                view=ReplyView("Only the bot owner can use Sus Link.")
            )
            return
        urls = extract_urls(message.content)
        if not urls:
            await interaction.edit_original_response(
                view=ReplyView(
                    "No supported public HTTP or HTTPS links were found in this message."
                )
            )
        elif len(urls) > 1:
            await interaction.edit_original_response(
                view=LinkPicker(self.bot, self, urls)
            )
        else:
            await self.scan(interaction, urls[0])

    async def scan(self, interaction, url):
        scanner = self.bot.scanner
        if scanner.lock.locked():
            await interaction.edit_original_response(
                view=ReplyView("A scan is already running. Try again once it finishes.")
            )
            return
        async with scanner.lock:
            progress = Progress(interaction)
            try:
                await progress.start()
                scan, picture = await scanner.run(url, progress.set)
                await progress.stop()
                await interaction.edit_original_response(
                    view=ReportView(self.bot, self, scan, picture, url)
                )
            except Exception as error:
                await progress.stop()
                log.error("Sus Link scan failed (%s)", type(error).__name__)
                from services.instabox import InstaboxError

                if isinstance(error, InstaboxError):
                    message = str(error)
                elif isinstance(error, RuntimeError):
                    message = str(error)
                else:
                    message = "The scan could not finish. Check the bot setup and provider status, then try again."
                await interaction.edit_original_response(
                    view=ReplyView(
                        "## Sus Link · Scan incomplete\n"
                        + display(message)
                        + "\n\nNo safety verdict was produced.",
                        accent_color=COLORS["Inconclusive"],
                    )
                )


async def setup(bot):
    await bot.add_cog(SusLink(bot))
