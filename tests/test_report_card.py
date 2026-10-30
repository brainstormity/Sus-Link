import asyncio
import io
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from core import Bot
from cogs.SusLink import SusLink
from services.analysis import evaluate
from services.report_card import render_score_card


class GaugeTests(unittest.TestCase):
    def test_all_verdicts_render_small_valid_pngs(self):
        for verdict, score in [
            ("Low risk", 0),
            ("Suspicious", 42),
            ("High risk", 100),
            ("Inconclusive", 0),
        ]:
            with self.subTest(verdict=verdict):
                report = {
                    "verdict": verdict,
                    "score": score,
                    "ai": {"confidence": "medium"},
                }
                output = render_score_card(report)
                with Image.open(io.BytesIO(output)) as picture:
                    self.assertEqual(picture.size, (1200, 420))
                    self.assertEqual(picture.format, "PNG")
                    picture.verify()
                self.assertLess(len(output), 250_000)
                if verdict == "Inconclusive":
                    self.assertNotEqual(
                        output, render_score_card({**report, "verdict": "Low risk"})
                    )


class GaugeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rendering_uses_worker_thread_and_attaches_card(self):
        bot = Bot()
        report = {
            **evaluate({"loaded": True}),
            "ai": {
                "confidence": "medium",
                "summary": "Test",
                "recommendation": "Review evidence",
            },
        }
        scan = SimpleNamespace(
            report=report,
            model="test",
            evidence={},
            created_at=datetime.now(timezone.utc),
        )
        bot.scanner = SimpleNamespace(
            lock=asyncio.Lock(), run=AsyncMock(return_value=(scan, b""))
        )
        dm = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(create_dm=AsyncMock(return_value=dm)),
            edit_original_response=AsyncMock(),
        )
        main_thread = threading.get_ident()

        def render(report):
            self.assertNotEqual(threading.get_ident(), main_thread)
            return render_score_card(report)

        with patch("cogs.SusLink.render_score_card", side_effect=render):
            await SusLink(bot).scan(interaction, "https://example.com")
        files = dm.send.call_args.kwargs["files"]
        self.assertEqual([file.filename for file in files], ["risk-score.png"])
        payload = str(dm.send.call_args.kwargs["view"].to_components())
        self.assertIn("attachment://risk-score.png", payload)
        await bot.close()

    async def test_rendering_failure_preserves_report_delivery(self):
        bot = Bot()
        report = {
            **evaluate({"loaded": True}),
            "ai": {
                "confidence": "medium",
                "summary": "Test",
                "recommendation": "Review evidence",
            },
        }
        scan = SimpleNamespace(
            report=report,
            model="test",
            evidence={},
            created_at=datetime.now(timezone.utc),
        )
        bot.scanner = SimpleNamespace(
            lock=asyncio.Lock(), run=AsyncMock(return_value=(scan, b""))
        )
        dm = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(create_dm=AsyncMock(return_value=dm)),
            edit_original_response=AsyncMock(),
        )
        with patch(
            "cogs.SusLink.render_score_card", side_effect=OSError("font unavailable")
        ):
            await SusLink(bot).scan(interaction, "https://example.com")
        self.assertNotIn(
            "attachment://risk-score.png",
            str(dm.send.call_args.kwargs["view"].to_components()),
        )
        self.assertEqual(dm.send.call_args.kwargs["files"], [])
        self.assertIn(
            "## Recommendation", str(dm.send.call_args.kwargs["view"].to_components())
        )
        await bot.close()
