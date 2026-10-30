from __future__ import annotations

import asyncio
import io
import logging
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from core.reply import ReplyView
from services.report_card import render_score_card
from services.sample_report import sample_scan, render_sample_assets
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


def report_heading(verdict, message_url=None):
    reference = f" · {message_url}" if message_url else ""
    return f"## {verdict}{reference}\n"


class ReportView(OwnerView):
    def __init__(self, bot, scan, picture, message_url=None, *, score_card=False):
        self.scan = scan
        report, ai = scan.report, scan.report["ai"]
        body = (
            f"{display(ai['summary'], 700)}\n"
            f"## Recommendation\n{display(ai['recommendation'], 550)}"
        )
        super().__init__(
            bot,
            report_heading(report["verdict"], message_url),
            accent_color=COLORS[report["verdict"]],
            include_footer=False,
        )
        if score_card:
            self.add_header_image("attachment://risk-score.png")
        self.add_body(body)
        reasons = report.get("assessment_reasons", [])
        if reasons:
            self.add_separator(
                spacing=discord.SeparatorSpacing.small, visible=False
            ).add_body(
                "**Inspection Limits**\n"
                + "\n".join("> -# • " + display(reason, 240) for reason in reasons[:3])
            )
        findings = [f["finding"] for f in report["findings"][:3]]
        findings.extend(f"AI assessment: {item}" for item in ai.get("findings", [])[:3])
        findings = list(dict.fromkeys(findings))[:5]
        self.add_separator(
            spacing=discord.SeparatorSpacing.small, visible=False
        ).add_body(
            "**Observed Evidence**\n"
            + (
                "\n".join(f"> -# • {display(finding, 200)}" for finding in findings)
                if findings
                else "> -# See the assessment above for the reasoning behind this rating."
            )
        )
        if picture:
            self.add_header_image("attachment://sus-link.jpg")
        self.add_footer()

    async def evidence(self, interaction):
        report, ai = self.scan.report, self.scan.report["ai"]
        redirects = self.scan.evidence.get("redirects", [])
        text = "## Navigation\n" + (
            "\n".join(
                f"• HTTP {r['status']}: {display(r['url'], 220)}" for r in redirects[:8]
            )
            or "No navigation response captured."
        )
        text += "\n\n## AI interpretation\n" + (
            "\n".join("• " + display(x, 280) for x in ai["findings"][:5])
            or "No additional AI findings."
        )
        if ai.get("model_notes"):
            text += "\n\n## Model selection\n" + "\n".join(
                "• " + display(note, 180) for note in ai["model_notes"][:3]
            )
        text += "\n\n## Coverage and limitations\n" + display(
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
    def __init__(self, bot, cog, urls, message_url=None):
        super().__init__(bot, "## Sus Link\nChoose a link to inspect.")
        self.cog, self.urls, self.message_url = cog, urls, message_url
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
        await self.cog.scan(
            interaction, self.urls[int(self.select.values[0])], self.message_url
        )


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

    @app_commands.command(
        name="sample-report",
        description="Preview the report layout instantly using fictional data.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.choices(
        verdict=[
            app_commands.Choice(name="Low risk", value="low_risk"),
            app_commands.Choice(name="Suspicious", value="suspicious"),
            app_commands.Choice(name="High risk", value="high_risk"),
            app_commands.Choice(name="Inconclusive", value="inconclusive"),
        ]
    )
    async def sample_report(
        self, interaction: discord.Interaction, verdict: str = "suspicious"
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await self.bot.is_owner(interaction.user):
            await interaction.edit_original_response(
                view=ReplyView("Only the bot owner can use Sus Link.")
            )
            return
        scan = sample_scan(verdict)
        card, picture = await asyncio.to_thread(render_sample_assets, scan.report)
        await interaction.edit_original_response(
            view=ReportView(self.bot, scan, picture, "SAMPLE REPORT", score_card=True),
            attachments=[
                discord.File(io.BytesIO(card), filename="risk-score.png"),
                discord.File(io.BytesIO(picture), filename="sus-link.jpg"),
            ],
        )

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
                view=LinkPicker(self.bot, self, urls, message.jump_url)
            )
        else:
            await self.scan(interaction, urls[0], message.jump_url)

    async def scan(self, interaction, url, message_url=None):
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
                content=f"Inspecting {url}. **I'll DM you the report once ready** 🤝"
            )
            try:
                scan, picture = await scanner.run(url)
                card = b""
                try:
                    card = await asyncio.to_thread(
                        render_score_card,
                        {
                            **scan.report,
                            "model": scan.model,
                            "domain": urlsplit(url).hostname,
                        },
                    )
                except Exception as render_error:
                    log.warning(
                        "Report gauge unavailable (%s); sending text report.",
                        type(render_error).__name__,
                    )
                view = ReportView(
                    self.bot, scan, picture, message_url, score_card=bool(card)
                )
                files = (
                    [discord.File(io.BytesIO(picture), filename="sus-link.jpg")]
                    if picture
                    else []
                )
                if card:
                    files.append(
                        discord.File(io.BytesIO(card), filename="risk-score.png")
                    )
            except Exception as error:
                log.error("Sus Link scan failed (%s)", type(error).__name__)
                from services.instabox import InstaboxError

                if isinstance(error, (InstaboxError, RuntimeError)):
                    message = str(error)
                else:
                    message = "The scan could not finish. Check the bot setup and provider status, then try again."
                view = ReplyView(
                    report_heading("Scan incomplete", message_url)
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
                    content=None,
                    view=ReplyView(
                        "I couldn't DM your report. Enable direct messages from this bot, "
                        "then run Sus Link Checker again."
                    ),
                )


async def setup(bot):
    await bot.add_cog(SusLink(bot))
