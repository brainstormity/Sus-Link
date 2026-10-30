import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.analysis import evaluate
from services.assessment import combine
from workers.browser_scan import detect_challenge, navigate, settle_page


class CoverageTests(unittest.TestCase):
    def test_unavailable_page_has_specific_reason(self):
        evidence = {"loaded": False, "status": 404, "text": "Page not found"}
        rules = evaluate(evidence)
        report = combine(evidence, rules, {"assessment": "low_risk"}, "test")
        self.assertEqual(report["verdict"], "Inconclusive")
        self.assertIn("HTTP 404", report["assessment_reasons"][0])

    def test_readable_page_can_be_low_risk_without_ownership_data(self):
        evidence = {
            "loaded": True,
            "status": 200,
            "content_captured": True,
            "text": "Project information",
            "final_url": "https://example.com",
        }
        report = combine(
            evidence, evaluate(evidence), {"assessment": "low_risk"}, "test"
        )
        self.assertEqual(report["verdict"], "Low risk")
        self.assertFalse(report["assessment_reasons"])

    def test_concrete_warning_is_not_hidden_by_partial_coverage_or_missing_ai(self):
        evidence = {
            "loaded": False,
            "status": 403,
            "downloads": ["https://example.com/file"],
            "text": "Your computer is infected",
        }
        rules = evaluate(evidence)
        report = combine(evidence, rules, {"assessment": "inconclusive"}, "")
        self.assertEqual(report["verdict"], "High risk")
        self.assertTrue(report["assessment_reasons"])
        self.assertEqual(report["inspection_status"], "limited")

    def test_ai_detected_phishing_can_warn_on_challenge_page(self):
        evidence = {"loaded": True, "challenge": True}
        report = combine(
            evidence, evaluate(evidence), {"assessment": "suspicious"}, "test"
        )
        self.assertEqual(report["verdict"], "Suspicious")
        self.assertTrue(report["assessment_reasons"])

    def test_empty_or_missing_content_cannot_be_low_risk(self):
        for missing in ({"content_captured": False}, {"content_empty": True}):
            evidence = {"loaded": True, **missing}
            report = combine(
                evidence, evaluate(evidence), {"assessment": "low_risk"}, "test"
            )
            self.assertEqual(report["verdict"], "Inconclusive")

    def test_screenshot_failure_does_not_discard_readable_content(self):
        evidence = {
            "loaded": True,
            "content_captured": True,
            "screenshot_captured": False,
            "errors": ["Screenshot failed"],
            "text": "Readable page",
        }
        report = combine(
            evidence, evaluate(evidence), {"assessment": "low_risk"}, "test"
        )
        self.assertEqual(report["verdict"], "Low risk")

    def test_ai_unavailable_without_warning_remains_inconclusive(self):
        evidence = {"loaded": True}
        report = combine(
            evidence, evaluate(evidence), {"assessment": "inconclusive"}, ""
        )
        self.assertEqual(report["verdict"], "Inconclusive")
        self.assertIn("AI analysis", report["assessment_reasons"][0])

    def test_challenge_detection_distinguishes_articles_and_bot_checks(self):
        self.assertTrue(detect_challenge("Robot Check", "Type the characters you see"))
        self.assertTrue(detect_challenge("Just a moment...", "Verifying..."))
        self.assertTrue(detect_challenge("Continue", "Please verify you are human"))
        self.assertFalse(
            detect_challenge(
                "Understanding CAPTCHA", "An article about captcha systems."
            )
        )
        self.assertFalse(
            detect_challenge(
                "Documentation", "Discussion of verify you are human. " * 100
            )
        )


class OverallScoreTests(unittest.TestCase):
    def test_ai_high_risk_with_zero_rule_signals_is_not_zero_risk(self):
        evidence = {"loaded": True}
        report = combine(
            evidence,
            evaluate(evidence),
            {"assessment": "high_risk", "risk_score": 87},
            "test",
        )
        self.assertEqual(report["rule_score"], 0)
        self.assertEqual(report["score"], 87)
        self.assertEqual(report["verdict"], "High risk")

    def test_warning_rules_cannot_be_lowered_by_ai(self):
        evidence = {
            "loaded": True,
            "downloads": ["file"],
            "text": "Your computer is infected",
        }
        report = combine(
            evidence,
            evaluate(evidence),
            {"assessment": "low_risk", "risk_score": 10},
            "test",
        )
        self.assertEqual(report["score"], 75)
        self.assertEqual(report["verdict"], "High risk")

    def test_score_bands_agree_with_verdict_at_boundaries(self):
        evidence = {"loaded": True}
        for score, assessment, verdict in [
            (0, "low_risk", "Low risk"),
            (24, "low_risk", "Low risk"),
            (25, "suspicious", "Suspicious"),
            (59, "suspicious", "Suspicious"),
            (60, "high_risk", "High risk"),
            (100, "high_risk", "High risk"),
        ]:
            with self.subTest(score=score):
                report = combine(
                    evidence,
                    evaluate(evidence),
                    {"assessment": assessment, "risk_score": score},
                    "test",
                )
                self.assertEqual(report["score"], score)
                self.assertEqual(report["verdict"], verdict)

    def test_inconclusive_has_no_overall_score(self):
        evidence = {"loaded": False, "status": 404}
        report = combine(
            evidence,
            evaluate(evidence),
            {"assessment": "inconclusive", "risk_score": 0},
            "test",
        )
        self.assertIsNone(report["score"])
        self.assertEqual(report["rule_score"], 0)

    def test_legacy_high_risk_assessment_is_normalized_to_high_risk_band(self):
        evidence = {"loaded": True}
        report = combine(
            evidence,
            evaluate(evidence),
            {"assessment": "high_risk", "risk_score": 0},
            "test",
        )
        self.assertEqual(report["score"], 60)
        self.assertEqual(report["verdict"], "High risk")


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def page(self):
        return SimpleNamespace(url="https://example.com", wait_for_timeout=AsyncMock())

    async def test_transient_challenge_is_allowed_to_clear(self):
        page = self.page()
        challenge = {
            "title": "Robot Check",
            "text": "Please verify you are human",
            "forms": [],
        }
        ready = {"title": "Project", "text": "Readable information. " * 20, "forms": []}
        with patch(
            "workers.browser_scan.snapshot",
            new=AsyncMock(side_effect=[challenge] * 4 + [ready] * 3),
        ):
            result, seconds = await settle_page(page)
        self.assertEqual(result["title"], "Project")
        self.assertEqual(seconds, 7)

    async def test_blank_page_wait_is_bounded(self):
        page = self.page()
        with patch(
            "workers.browser_scan.snapshot",
            new=AsyncMock(return_value={"title": "", "text": "", "forms": []}),
        ):
            _, seconds = await settle_page(page)
        self.assertEqual(seconds, 12)
        self.assertEqual(page.wait_for_timeout.await_count, 12)

    async def test_server_error_retries_but_404_does_not(self):
        page = self.page()
        page.goto = AsyncMock(
            side_effect=[SimpleNamespace(status=503), SimpleNamespace(status=200)]
        )
        evidence = {"errors": []}
        await navigate(page, page.url, evidence)
        self.assertEqual(evidence["status"], 200)
        self.assertEqual(evidence["navigation_attempts"], 2)
        page.goto = AsyncMock(return_value=SimpleNamespace(status=404))
        await navigate(page, page.url, evidence)
        self.assertEqual(evidence["navigation_attempts"], 1)
        self.assertEqual(evidence["status"], 404)

    async def test_navigation_timeout_recovers_on_retry(self):
        page = self.page()
        page.goto = AsyncMock(side_effect=[TimeoutError(), SimpleNamespace(status=200)])
        evidence = {"errors": []}
        await navigate(page, page.url, evidence)
        self.assertEqual(evidence["status"], 200)
        self.assertEqual(evidence["navigation_attempts"], 2)

    async def test_timeout_does_not_retry_when_main_response_already_arrived(self):
        page = self.page()
        evidence = {"errors": []}

        async def already_rendered(*args, **kwargs):
            evidence["status"] = 200
            raise TimeoutError()

        page.goto = AsyncMock(side_effect=already_rendered)
        await navigate(page, page.url, evidence)
        page.goto.assert_awaited_once()
        self.assertEqual(evidence["status"], 200)
