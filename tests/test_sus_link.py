import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tortoise import Tortoise

from core import Bot, config
from core.models import MachineState, ModelState, Scan
from services.analysis import Gemini, cooldown, evaluate, next_reset
from services.instabox import Instabox, InstaboxError
from services.urls import extract_urls, redact_url, validate_url
from workers.browser_scan import PublicProxy, public_ip


class URLTests(unittest.TestCase):
    def test_markdown_dedup_and_balanced_parentheses(self):
        self.assertEqual(
            extract_urls(
                "[one](https://example.com/a) <https://example.com/a> "
                "https://example.org/wiki/Test_(thing)."
            ),
            ["https://example.com/a", "https://example.org/wiki/Test_(thing)"],
        )

    def test_reject_local_and_nonweb_urls(self):
        for url in [
            "file:///etc/passwd",
            "http://127.0.0.1",
            "http://169.254.169.254/",
            "http://localhost/",
            "https://secret.internal/",
            "https://user:pass@example.com/",
            "https://example.com:22/",
            "https://example.com/\\@localhost",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)
        self.assertEqual(
            extract_urls("http://localhost https://example.com"),
            ["https://example.com/"],
        )

    def test_redaction(self):
        self.assertEqual(
            redact_url("https://example.com/a?token=private#secret"),
            "https://example.com/a?[redacted]",
        )

    def test_reserved_addresses(self):
        for ip in [
            "127.0.0.1",
            "169.254.169.254",
            "10.1.2.3",
            "::1",
            "::ffff:127.0.0.1",
            "224.0.0.1",
        ]:
            self.assertFalse(public_ip(ip), ip)
        self.assertTrue(public_ip("8.8.8.8"))


class AssessmentTests(unittest.TestCase):
    def test_failed_and_challenged_pages_never_low_risk(self):
        self.assertEqual(evaluate({"loaded": False})["verdict"], "Inconclusive")
        self.assertEqual(
            evaluate({"loaded": True, "challenge": True})["verdict"], "Inconclusive"
        )

    def test_password_alone_is_not_phishing(self):
        evidence = {
            "loaded": True,
            "final_url": "https://example.com",
            "forms": [
                {
                    "action": "https://example.com/login",
                    "inputs": [{"type": "password"}],
                }
            ],
        }
        self.assertEqual(evaluate(evidence)["score"], 10)
        evidence["forms"][0]["action"] = "http://other.example/login"
        self.assertEqual(evaluate(evidence)["verdict"], "High risk")

    def test_quota_cooldowns_and_dst(self):
        at = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(next_reset(at), datetime(2026, 10, 30, 7, tzinfo=timezone.utc))
        error = {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                },
                {"retryDelay": "30s"},
            ]
        }
        self.assertEqual(cooldown(error, at), (next_reset(at), "daily_quota"))
        self.assertEqual(
            cooldown({"details": [{"retryDelay": "30s"}]}, at)[0],
            at + timedelta(seconds=30),
        )
        self.assertEqual(cooldown({}, at)[0], at + timedelta(hours=24))
        # Pacific midnight following the fall-back day is 25 hours later.
        dst = datetime(2026, 11, 1, 7, tzinfo=timezone.utc)
        self.assertEqual(next_reset(dst) - dst, timedelta(hours=25))


class FakeResponse:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return self.data


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await Tortoise.init(
            db_url="sqlite://:memory:", modules={"models": ["core.models"]}, use_tz=True
        )
        await Tortoise.generate_schemas()

    async def asyncTearDown(self):
        await Tortoise.close_connections()

    async def test_resume_existing_machine_without_recreate(self):
        machine = {
            "id": "m_test",
            "name": "sus-link",
            "state": "suspended",
            "metadata": {"app": "sus-link"},
            "runtime": {"ready": False},
        }
        from services.instabox import WORKER, SETUP
        import hashlib

        version = hashlib.sha256(WORKER.read_bytes() + SETUP.encode()).hexdigest()
        await MachineState.create(
            name=config.INSTABOX_MACHINE_NAME,
            machine_id="m_test",
            setup_version=version,
        )
        client = Instabox(None)
        running = {**machine, "state": "running", "runtime": {"ready": True}}
        client.request = AsyncMock(
            side_effect=[
                machine,
                {"id": "op_test", "state": "succeeded", "machineId": "m_test"},
                running,
            ]
        )
        self.assertEqual(await client.ensure_machine(), "m_test")
        self.assertEqual(
            client.request.call_args_list[1].args, ("POST", "/machines/m_test/resume")
        )

    async def test_create_missing_machine_with_secrets_disabled(self):
        from services.instabox import WORKER, SETUP
        import hashlib

        version = hashlib.sha256(WORKER.read_bytes() + SETUP.encode()).hexdigest()
        # Keep setup marked complete only after returning the same machine ID.
        await MachineState.create(
            name=config.INSTABOX_MACHINE_NAME, machine_id="m_old", setup_version=""
        )
        client = Instabox(None)
        machine = {
            "id": "m_new",
            "state": "running",
            "metadata": {"app": "sus-link"},
            "runtime": {"ready": True},
        }
        client.request = AsyncMock(
            side_effect=[
                InstaboxError("not_found", 404),
                InstaboxError("not_found", 404),
                {"id": "op_test", "state": "succeeded", "machineId": "m_new"},
                machine,
                {},
            ]
        )
        client.exec = AsyncMock(return_value="")
        self.assertEqual(await client.ensure_machine(), "m_new")
        create = client.request.call_args_list[2]
        self.assertEqual(create.kwargs["json"]["secrets"], [])
        self.assertFalse(create.kwargs["json"]["vault"])
        self.assertEqual(
            (await MachineState.get(name=config.INSTABOX_MACHINE_NAME)).setup_version,
            version,
        )

    async def test_failed_operation_stops_before_exec(self):
        client = Instabox(None)
        with self.assertRaises(InstaboxError):
            await client.wait_operation(
                {"state": "failed", "error": {"code": "no_capacity"}}
            )

    async def test_lifecycle_retries_keep_idempotency_key(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        session.request.side_effect = [
            FakeResponse(
                503, {"error": {"code": "host_unavailable", "retryable": True}}
            ),
            FakeResponse(202, {"id": "op_ok"}),
        ]
        with patch("services.instabox.asyncio.sleep", new=AsyncMock()):
            await Instabox(session).request(
                "POST", "/machines", lifecycle=True, json={}
            )
        calls = session.request.call_args_list
        self.assertEqual(
            calls[0].kwargs["headers"]["Idempotency-Key"],
            calls[1].kwargs["headers"]["Idempotency-Key"],
        )

    async def test_model_fallback_persists_daily_limit(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        report = {
            "summary": "Review complete",
            "recommendation": "Use caution",
            "confidence": "medium",
            "assessment": "suspicious",
            "findings": ["An observation"],
            "limitations": [],
        }
        error = {
            "error": {
                "details": [
                    {"@type": "google.rpc.QuotaFailure", "quotaId": "RequestsPerDay"}
                ]
            }
        }
        session.post.side_effect = [
            FakeResponse(429, error),
            FakeResponse(
                200,
                {
                    "candidates": [
                        {"content": {"parts": [{"text": json.dumps(report)}]}}
                    ]
                },
            ),
        ]
        with patch.object(config, "GEMINI_MODELS", ("first", "second")), patch.object(
            config, "GEMINI_DAILY_BUDGETS", (20, 20)
        ):
            result, model = await Gemini(session).analyze({"loaded": True}, "", {})
            self.assertEqual(model, "second")
            state = await ModelState.get(name="first")
            self.assertEqual(state.reason, "daily_quota")
            self.assertIsNotNone(state.retry_at)
            self.assertEqual(state.requests, 1)
            # Next scan skips the cooled-down first model.
            session.post.side_effect = [
                FakeResponse(
                    200,
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": json.dumps(report)}]}}
                        ]
                    },
                )
            ]
            await Gemini(session).analyze({}, "", {})
            self.assertIn("/second:", session.post.call_args.args[0])

    async def test_high_demand_retries_then_falls_back_without_quota_cooldown(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        report = {
            "summary": "Test",
            "recommendation": "Use caution",
            "confidence": "low",
            "assessment": "low_risk",
            "findings": [],
            "limitations": [],
        }
        success = {
            "candidates": [{"content": {"parts": [{"text": json.dumps(report)}]}}]
        }
        session.post.side_effect = [
            FakeResponse(503, {"error": {"status": "UNAVAILABLE"}}),
            FakeResponse(503, {"error": {"status": "UNAVAILABLE"}}),
            FakeResponse(200, success),
        ]
        with patch.object(config, "GEMINI_MODELS", ("first", "second")), patch(
            "services.analysis.asyncio.sleep", new=AsyncMock()
        ):
            result, model = await Gemini(session).analyze({}, "", {})
            self.assertEqual(model, "second")
            self.assertEqual(session.post.call_count, 3)
            self.assertTrue(
                all(
                    "/first:" in call.args[0]
                    for call in session.post.call_args_list[:2]
                )
            )
            self.assertIn("/second:", session.post.call_args.args[0])
            self.assertIn("high demand", result["model_notes"][0])
            state = await ModelState.get(name="first")
            self.assertEqual(state.requests, 2)
            self.assertEqual(state.reason, "provider_high_demand")
            self.assertIsNone(state.retry_at)
            self.assertIsNone(state.limited_at)
            session.post.side_effect = [FakeResponse(200, success)]
            _, model = await Gemini(session).analyze({}, "", {})
            self.assertEqual(model, "first")
            self.assertIn("/first:", session.post.call_args.args[0])

    async def test_invalid_output_does_not_downgrade(self):
        from unittest.mock import MagicMock

        session = MagicMock()
        session.post.return_value = FakeResponse(
            200,
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "truncated JSON"}]},
                        "finishReason": "MAX_TOKENS",
                    }
                ]
            },
        )
        with patch.object(config, "GEMINI_MODELS", ("first", "second")):
            result, model = await Gemini(session).analyze({}, "", {})
        self.assertEqual(model, "")
        self.assertEqual(session.post.call_count, 1)
        self.assertIsNone(await ModelState.get_or_none(name="second"))
        self.assertIn("invalid response", result["limitations"][0])

    async def test_all_models_exhausted_returns_evidence_only(self):
        from unittest.mock import MagicMock

        at = datetime.now(timezone.utc)
        await ModelState.create(name="limited", retry_at=at + timedelta(hours=1))
        session = MagicMock()
        with patch.object(config, "GEMINI_MODELS", ("limited",)):
            result, model = await Gemini(session).analyze({}, "", {})
        self.assertFalse(model)
        self.assertEqual(result["assessment"], "inconclusive")
        session.post.assert_not_called()

    async def test_ai_unavailable_makes_scan_inconclusive(self):
        from services.scanner import Scanner

        scanner = Scanner(None)
        scanner.instabox.ensure_machine = AsyncMock(return_value="m_test")
        scanner.instabox.collect = AsyncMock(
            return_value={
                "evidence": {"loaded": True, "final_url": "https://example.com/"},
                "screenshot": "",
            }
        )
        scanner.gemini.analyze = AsyncMock(
            return_value=({"assessment": "inconclusive"}, "")
        )
        with patch.object(config, "INSTABOX_API", "test"), patch.object(
            config, "GEMINI_API", "test"
        ):
            scan, _ = await scanner.run("https://example.com/?token=secret")
        self.assertEqual(scan.report["verdict"], "Inconclusive")
        self.assertNotIn("secret", scan.url)


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    async def test_component_owner_check(self):
        from cogs.SusLink import OwnerView

        bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
        interaction = SimpleNamespace(
            user=object(), response=SimpleNamespace(send_message=AsyncMock())
        )
        self.assertFalse(await OwnerView(bot, "test").interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_context_command_denies_nonowner_before_scan(self):
        from cogs.SusLink import SusLink

        bot = Bot()
        bot.is_owner = AsyncMock(return_value=False)
        cog = SusLink(bot)
        cog.scan = AsyncMock()
        interaction = SimpleNamespace(
            user=object(),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        await cog.check_message(
            interaction, SimpleNamespace(content="https://example.com")
        )
        cog.scan.assert_not_called()
        self.assertFalse(bot.intents.message_content)
        self.assertTrue(interaction.response.defer.call_args.kwargs["ephemeral"])
        await bot.close()

    async def test_finished_report_is_dmed_after_single_acknowledgement(self):
        from cogs.SusLink import SusLink

        bot = Bot()
        scan = SimpleNamespace(
            evidence={},
            model="test",
            created_at=datetime.now(timezone.utc),
            report={
                **evaluate({"loaded": True}),
                "ai": {
                    "summary": "Complete",
                    "recommendation": "Review evidence",
                    "confidence": "medium",
                },
            },
        )
        bot.scanner = SimpleNamespace(
            lock=asyncio.Lock(), run=AsyncMock(return_value=(scan, b"image"))
        )
        dm = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(create_dm=AsyncMock(return_value=dm)),
            edit_original_response=AsyncMock(),
        )
        await SusLink(bot).scan(
            interaction, "https://example.com", "https://discord.com/channels/1/2/3"
        )
        interaction.edit_original_response.assert_awaited_once()
        ack = json.dumps(
            interaction.edit_original_response.call_args.kwargs["view"].to_components()
        )
        self.assertIn("Inspecting link", ack)
        dm.send.assert_awaited_once()
        self.assertIn(
            "https://discord.com/channels/1/2/3",
            json.dumps(dm.send.call_args.kwargs["view"].to_components()),
        )
        self.assertEqual(dm.send.call_args.kwargs["files"][0].filename, "sus-link.jpg")
        self.assertNotIn("ephemeral", dm.send.call_args.kwargs)
        bot.scanner.run.assert_awaited_once_with("https://example.com")
        await bot.close()

    async def test_dm_channel_failure_prevents_scan(self):
        import discord
        from cogs.SusLink import SusLink

        bot = Bot()
        bot.scanner = SimpleNamespace(lock=asyncio.Lock(), run=AsyncMock())
        response = SimpleNamespace(status=403, reason="Forbidden")
        interaction = SimpleNamespace(
            user=SimpleNamespace(
                create_dm=AsyncMock(
                    side_effect=discord.Forbidden(response, "Cannot send messages")
                )
            ),
            edit_original_response=AsyncMock(),
        )
        await SusLink(bot).scan(interaction, "https://example.com")
        bot.scanner.run.assert_not_called()
        self.assertIn(
            "couldn't open your DMs",
            json.dumps(
                interaction.edit_original_response.call_args.kwargs[
                    "view"
                ].to_components()
            ),
        )
        await bot.close()

    async def test_scan_failure_is_reported_by_dm(self):
        from cogs.SusLink import SusLink

        bot = Bot()
        bot.scanner = SimpleNamespace(
            lock=asyncio.Lock(), run=AsyncMock(side_effect=RuntimeError("Missing key"))
        )
        dm = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(create_dm=AsyncMock(return_value=dm)),
            edit_original_response=AsyncMock(),
        )
        await SusLink(bot).scan(interaction, "https://example.com")
        self.assertIn(
            "Scan incomplete",
            json.dumps(dm.send.call_args.kwargs["view"].to_components()),
        )
        interaction.edit_original_response.assert_awaited_once()
        await bot.close()

    async def test_report_and_selector_serialize_as_v2(self):
        from cogs.SusLink import ReportView, LinkPicker

        bot = Bot()
        ai = {
            "summary": "@everyone https://bad.example/test",
            "recommendation": "Be careful",
            "confidence": "medium",
            "findings": [],
            "limitations": [],
        }
        scan = SimpleNamespace(
            evidence={"final_url": "https://example.com"},
            report={**evaluate({"loaded": True}), "ai": ai},
            model="test",
            created_at=datetime.now(timezone.utc),
        )
        source_url = "https://discord.com/channels/@me/123/456"
        view = ReportView(bot, scan, b"image", source_url)
        self.assertEqual(view.to_components()[0]["type"], 17)
        self.assertLessEqual(view.content_length(), 4000)
        payload = json.dumps(view.to_components())
        self.assertIn("attachment://sus-link.jpg", payload)
        self.assertIn(f"[#original-message]({source_url})", payload)
        self.assertNotIn("Final destination", payload)
        self.assertNotIn("Captured page", payload)
        self.assertNotIn("Sus Link ·", payload)
        self.assertIn("## Recommendation", payload)
        self.assertIn("## Observed evidence", payload)
        self.assertNotIn("Prepare isolated browser", payload)
        buttons = [
            item.label
            for item in view.walk_children()
            if isinstance(item, __import__("discord").ui.Button)
        ]
        self.assertEqual(buttons, [])
        self.assertFalse(hasattr(view, "rescan"))
        self.assertTrue(callable(view.evidence))
        self.assertFalse(hasattr(view, "full_report"))
        self.assertEqual(
            LinkPicker(bot, None, ["https://example.com"]).to_components()[0]["type"],
            17,
        )
        await bot.close()


if __name__ == "__main__":
    unittest.main()


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebinding_to_private_address_never_connects(self):
        import socket

        proxy = PublicProxy()
        reader = asyncio.StreamReader()
        reader.feed_data(b"CONNECT looks-public.example:443 HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        writer = SimpleNamespace(close=lambda: None)
        loop = asyncio.get_running_loop()
        private = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))
        ]
        with patch.object(
            loop, "getaddrinfo", new=AsyncMock(return_value=private)
        ), patch(
            "workers.browser_scan.asyncio.open_connection", new=AsyncMock()
        ) as connect:
            await proxy.handle(reader, writer)
        connect.assert_not_called()
        self.assertEqual(proxy.blocked, ["looks-public.example"])

    async def test_proxy_connects_to_validated_numeric_ip(self):
        import socket
        from unittest.mock import MagicMock

        proxy = PublicProxy()
        reader = asyncio.StreamReader()
        reader.feed_data(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        incoming = asyncio.StreamReader()
        incoming.feed_eof()
        writer = MagicMock()
        writer.drain = AsyncMock()
        upstream = MagicMock()
        upstream.drain = AsyncMock()
        loop = asyncio.get_running_loop()
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch.object(
            loop, "getaddrinfo", new=AsyncMock(return_value=public)
        ), patch(
            "workers.browser_scan.asyncio.open_connection",
            new=AsyncMock(return_value=(incoming, upstream)),
        ) as connect:
            await proxy.handle(reader, writer)
        connect.assert_awaited_once_with("93.184.215.14", 443)
        writer.write.assert_called_with(b"HTTP/1.1 200 Connection Established\r\n\r\n")
