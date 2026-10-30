from __future__ import annotations

import asyncio
import base64
import logging

from core import config
from core.models import Scan
from services.analysis import Gemini, evaluate, now
from services.assessment import combine
from services.instabox import Instabox
from services.urls import redact_url

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, session):
        self.lock = asyncio.Lock()
        self.instabox = Instabox(session)
        self.gemini = Gemini(session)

    async def run(self, url):
        if not config.INSTABOX_API or not config.GEMINI_API:
            raise RuntimeError(
                "Set INSTABOX_API and GEMINI_API in .env before scanning."
            )
        scan = await Scan.create(url=redact_url(url))
        try:
            async with asyncio.timeout(660):
                machine = await self.instabox.ensure_machine()
                captured = await self.instabox.collect(machine, url)
                evidence = captured["evidence"]
                rules = evaluate(evidence)
                ai, model = await self.gemini.analyze(
                    evidence, captured.get("screenshot", ""), rules
                )
                report = combine(evidence, rules, ai, model)
                scan.evidence, scan.report, scan.model = evidence, report, model
                scan.status, scan.completed_at = "complete", now()
                await scan.save()
                picture = base64.b64decode(
                    captured.get("screenshot", ""), validate=True
                )
                return scan, picture
        except BaseException:
            scan.status, scan.completed_at = "failed", now()
            await scan.save()
            raise
