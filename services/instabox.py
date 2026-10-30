from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from pathlib import Path

import aiohttp

from core import config
from core.models import MachineState

BASE = "https://api.instabox.sh/v1"
WORKER = Path(__file__).resolve().parents[1] / "workers" / "browser_scan.py"
# This script is fixed application code. User URLs are supplied separately via stdin.
SETUP = """set -eu
python3 -m venv /data/sus-link-venv
/data/sus-link-venv/bin/pip install --disable-pip-version-check 'playwright==1.64.1'
/data/sus-link-venv/bin/python -m playwright install chromium
"""


class InstaboxError(RuntimeError):
    def __init__(self, code, status=0):
        self.code, self.status = code, status
        super().__init__(f"Instabox: {code} (HTTP {status})")


class Instabox:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def request(self, method, path, *, lifecycle=False, **kwargs):
        headers = {"X-API-Key": config.INSTABOX_API}
        if lifecycle:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        for attempt in range(3):
            try:
                async with self.session.request(
                    method, BASE + path, headers=headers, **kwargs
                ) as response:
                    data = await response.json(content_type=None)
                    if response.status < 400:
                        return data
                    error = data.get("error", {})
                    if (
                        attempt < 2
                        and (method == "GET" or lifecycle)
                        and error.get("retryable")
                    ):
                        await asyncio.sleep(
                            min(
                                15,
                                max(
                                    1, float(error.get("retryAfterSeconds", 2**attempt))
                                ),
                            )
                        )
                        continue
                    raise InstaboxError(
                        error.get("code", "request_failed"), response.status
                    )
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                if attempt == 2 or (method != "GET" and not lifecycle):
                    raise InstaboxError("connection_failed") from None
                await asyncio.sleep(2**attempt)
        raise InstaboxError("retry_exhausted")

    async def wait_operation(self, operation):
        async with asyncio.timeout(240):
            while operation["state"] not in ("succeeded", "failed"):
                operation = await self.request(
                    "GET", f"/operations/{operation['id']}", params={"wait": "25s"}
                )
            if operation["state"] == "failed":
                raise InstaboxError(
                    (operation.get("error") or {}).get("code", "operation_failed")
                )
        return operation

    async def ensure_machine(self):
        name = config.INSTABOX_MACHINE_NAME
        saved = await MachineState.get_or_none(name=name)
        try:
            machine = await self.request(
                "GET", f"/machines/{saved.machine_id if saved else name}"
            )
        except InstaboxError as exc:
            if exc.status != 404:
                raise
            # Recover by deterministic name if a saved machine was removed/replaced.
            if saved:
                try:
                    machine = await self.request("GET", f"/machines/{name}")
                except InstaboxError as retry:
                    if retry.status != 404:
                        raise
                    machine = None
            else:
                machine = None
            if machine is None:
                operation = await self.request(
                    "POST",
                    "/machines",
                    lifecycle=True,
                    json={
                        "name": name,
                        "templateId": "agent-browser",
                        "vault": False,
                        "secrets": [],
                        "envSecrets": [],
                        "metadata": {"app": "sus-link"},
                    },
                )
                await self.wait_operation(operation)
                machine = await self.request(
                    "GET", f"/machines/{operation['machineId']}"
                )
        if machine.get("metadata", {}).get("app") != "sus-link":
            raise InstaboxError("machine_name_in_use_by_another_application")
        if not saved or saved.machine_id != machine["id"]:
            saved, _ = await MachineState.update_or_create(
                name=name,
                defaults={
                    "machine_id": machine["id"],
                    "setup_version": "",
                },
            )
        async with asyncio.timeout(240):
            while machine["state"] != "running" or not machine.get("runtime", {}).get(
                "ready", False
            ):
                if machine.get("operationId"):
                    await self.wait_operation(
                        {"id": machine["operationId"], "state": "running"}
                    )
                elif machine["state"] in ("suspended", "stopped"):
                    action = "resume" if machine["state"] == "suspended" else "start"
                    op = await self.request(
                        "POST", f"/machines/{machine['id']}/{action}", lifecycle=True
                    )
                    await self.wait_operation(op)
                elif machine["state"] in ("error", "deleting"):
                    raise InstaboxError("machine_" + machine["state"])
                else:
                    await asyncio.sleep(2)
                machine = await self.request("GET", f"/machines/{machine['id']}")
        source = WORKER.read_bytes()
        version = hashlib.sha256(source + SETUP.encode()).hexdigest()
        if saved.setup_version != version:
            await self.exec(machine["id"], ["bash", "-s"], SETUP, timeout=240)
            await self.request(
                "PUT",
                f"/machines/{machine['id']}/files",
                params={
                    "path": "/data/sus-link/browser_scan.py",
                    "parents": "true",
                },
                data=source,
            )
            saved.setup_version = version
            await saved.save()
        return machine["id"]

    async def exec(self, machine_id, argv, stdin="", timeout=120):
        data = await self.request(
            "POST",
            f"/machines/{machine_id}/exec",
            json={
                "argv": argv,
                "stdin": stdin,
                "timeoutSeconds": timeout,
            },
        )
        if data.get("exitCode") != 0 or data.get("timedOut") or data.get("truncated"):
            raise InstaboxError("browser_command_failed")
        return data["stdout"]

    async def collect(self, machine_id, url):
        output = await self.exec(
            machine_id,
            ["/data/sus-link-venv/bin/python", "/data/sus-link/browser_scan.py"],
            json.dumps({"url": url}),
            timeout=110,
        )
        return json.loads(output)
