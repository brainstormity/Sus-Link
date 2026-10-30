import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from core import Bot
from cogs.SusLink import ReportView, SusLink
from services.sample_report import SAMPLES


class SampleReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_sample_command_is_registered_for_user_and_dm_use(self):
        bot = Bot()
        await bot.add_cog(SusLink(bot))
        command = bot.tree.get_command("sample-report")
        self.assertIsNotNone(command)
        payload = command.to_dict(bot.tree)
        self.assertEqual(set(payload["integration_types"]), {0, 1})
        self.assertEqual(set(payload["contexts"]), {0, 1, 2})
        await bot.close()

    async def test_each_verdict_uses_real_layout_and_local_attachments(self):
        bot = Bot()
        bot.is_owner = AsyncMock(return_value=True)
        cog = SusLink(bot)
        # No scanner or provider clients exist on this bot: samples cannot call them.
        for kind in SAMPLES:
            with self.subTest(verdict=kind):
                interaction = SimpleNamespace(
                    user=object(),
                    response=SimpleNamespace(defer=AsyncMock()),
                    edit_original_response=AsyncMock(),
                )
                await cog.sample_report.callback(cog, interaction, kind)
                self.assertTrue(
                    interaction.response.defer.call_args.kwargs["ephemeral"]
                )
                result = interaction.edit_original_response.call_args.kwargs
                self.assertIsInstance(result["view"], ReportView)
                payload = str(result["view"].to_components())
                self.assertIn("SAMPLE REPORT", payload)
                self.assertIn("attachment://risk-score.png", payload)
                self.assertIn("attachment://sus-link.jpg", payload)
                self.assertLessEqual(result["view"].content_length(), 4000)
                self.assertEqual(
                    [file.filename for file in result["attachments"]],
                    ["risk-score.png", "sus-link.jpg"],
                )
                for file in result["attachments"]:
                    with Image.open(io.BytesIO(file.fp.getvalue())) as image:
                        image.verify()
        await bot.close()

    async def test_nonowner_cannot_generate_sample(self):
        bot = Bot()
        bot.is_owner = AsyncMock(return_value=False)
        cog = SusLink(bot)
        interaction = SimpleNamespace(
            user=object(),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        with patch("cogs.SusLink.render_sample_assets") as render:
            await cog.sample_report.callback(cog, interaction)
        render.assert_not_called()
        self.assertIn(
            "Only the bot owner",
            str(
                interaction.edit_original_response.call_args.kwargs[
                    "view"
                ].to_components()
            ),
        )
        await bot.close()
