from __future__ import annotations

import asyncio
import io
import logging
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from core.reply import ReplyView
from services.urls import extract_urls, redact_url

log = logging.getLogger(__name__)
COLORS = {
    "High risk": 0xED4245,
    "Suspicious": 0xFEE75C,
    "Low risk": 0x57F287,
    "Inconclusive": 0x99AAB5,
}


def display(value, limit=1500):
    # Preserve normal URLs while escaping untrusted Markdown and mentions.
    value = str(value)
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


class ReportView(OwnerView):
    def __init__(self, bot, scan, picture):
        self.scan = scan
        report, ai = scan.report, scan.report["ai"]
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
            "-# Score is rule-based, not a probability or guarantee of safety. "
            f"Model: {display(scan.model or 'unavailable', 80)} · {scan.created_at:%Y-%m-%d %H:%M UTC}"
        )
        if picture:
            self.add_separator().add_body("**Captured page**")
            self.add_header_image("attachment://sus-link.jpg")
        button = discord.ui.Button(
            label="Evidence - Full Trace", style=discord.ButtonStyle.primary
        )
        button.callback = self.evidence
        self._container.add_item(discord.ui.ActionRow(button))
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
        if ai.get("model_notes"):
            text += "\n\n**Model selection**\n" + "\n".join(
                "• " + display(note, 180) for note in ai["model_notes"][:3]
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
            name="Sus Link Checker",
            callback=self.check_message,
            allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
            allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=True
            ),
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
            try:
                dm = await interaction.user.create_dm()
            except discord.HTTPException:
                await interaction.edit_original_response(
                    view=ReplyView(
                        "I couldn't open your DMs. Enable direct messages from this bot and try again."
                    )
                )
                return
            await interaction.edit_original_response(
                view=ReplyView(
                    "Inspecting link. Your report will be sent to you by DM once ready."
                )
            )
            try:
                scan, picture = await scanner.run(url)
                view = ReportView(self.bot, scan, picture)
                files = (
                    [discord.File(io.BytesIO(picture), filename="sus-link.jpg")]
                    if picture
                    else []
                )
            except Exception as error:
                log.error("Sus Link scan failed (%s)", type(error).__name__)
                from services.instabox import InstaboxError

                if isinstance(error, (InstaboxError, RuntimeError)):
                    message = str(error)
                else:
                    message = "The scan could not finish. Check the bot setup and provider status, then try again."
                view = ReplyView(
                    "## Sus Link · Scan incomplete\n"
                    + display(message)
                    + "\n\nNo safety verdict was produced.",
                    accent_color=COLORS["Inconclusive"],
                )
                files = []
            try:
                # DM messages are private, ordinary messages; ephemeral only applies
                # to the command acknowledgement and component interaction replies.
                await dm.send(view=view, files=files)
            except discord.HTTPException:
                log.warning("Sus Link DM delivery failed.")
                await interaction.edit_original_response(
                    view=ReplyView(
                        "I couldn't DM your report. Enable direct messages from this bot, "
                        "then run Sus Link Checker again."
                    )
                )


async def setup(bot):
    await bot.add_cog(SusLink(bot))
