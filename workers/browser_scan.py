"""Runs only inside the dedicated Instabox VM. Never receives API credentials."""

import asyncio
import base64
import ipaddress
import json
import socket
import sys
from urllib.parse import urlsplit, urlunsplit


def public_ip(value):
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast


def safe_url(value):
    try:
        p = urlsplit(value)
        return urlunsplit(
            (p.scheme, p.netloc, p.path, "[redacted]" if p.query else "", "")
        )[:1000]
    except ValueError:
        return "[invalid URL]"


def detect_challenge(title, text):
    title = title.strip().lower()
    text = text.strip().lower()
    if title in (
        "robot check",
        "just a moment...",
        "just a moment",
        "access denied",
        "captcha",
    ):
        return True
    if "attention required" in title and "cloudflare" in title:
        return True
    # A mention of CAPTCHA in an article is not itself an access challenge.
    return len(text) < 2500 and any(
        phrase in text
        for phrase in (
            "verify you are human",
            "checking your browser",
            "verify that you are not a robot",
            "enter the characters you see",
            "type the characters you see",
            "complete the security check",
            "performing security verification",
            "sorry, we just need to make sure you're not a robot",
        )
    )


async def snapshot(page):
    return await page.evaluate("""() => ({
        title: document.title.slice(0, 300),
        text: (document.body?.innerText || '').slice(0, 18000),
        forms: [...document.forms].slice(0, 20).map(f => ({
            action: f.action, method: f.method,
            inputs: [...f.querySelectorAll('input')].slice(0, 30).map(i => ({
                type: i.type, name: i.name.slice(0,100),
                placeholder: i.placeholder.slice(0,150)}))})),
        frames: [...document.querySelectorAll('iframe')].slice(0,10).map(f=>f.src)
    })""")


async def settle_page(page):
    """Wait 4–12 seconds for readable, stable content; allow transient challenges to clear."""
    previous, stable, last = None, 0, None
    for elapsed in range(1, 13):
        await page.wait_for_timeout(1000)
        try:
            async with asyncio.timeout(2):
                last = await snapshot(page)
        except Exception:
            continue
        signature = (page.url, last["title"], last["text"])
        stable = stable + 1 if signature == previous else 0
        previous = signature
        readable = len(last["text"].strip()) >= 80 or bool(last["forms"])
        if (
            elapsed >= 4
            and stable >= 2
            and readable
            and not detect_challenge(last["title"], last["text"])
        ):
            return last, elapsed
    return last, 12


async def navigate(page, url, evidence):
    evidence["navigation_attempts"] = 0
    for attempt in range(2):
        evidence["navigation_attempts"] += 1
        evidence["status"] = None
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=25000 if attempt == 0 else 15000,
            )
            if response:
                evidence["status"] = response.status
        except Exception:
            evidence["errors"].append(
                "Navigation did not finish normally; any rendered content was still inspected."
            )
        status = evidence.get("status")
        if attempt == 0 and (status is None or status >= 500):
            await page.wait_for_timeout(1500)
            continue
        break


class PublicProxy:
    """Resolve once, validate every address, connect to the validated numeric IP.

    CONNECT is restricted to 443; HTTP to 80. Chromium has no direct fallback.
    This blocks browser requests to private destinations, including DNS rebinding.
    It is defense in depth, not containment against a browser/VM exploit.
    """

    def __init__(self):
        self.blocked = []
        self.tasks = set()
        self.limit = asyncio.Semaphore(24)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        try:
            async with asyncio.timeout(45), self.limit:
                header = await reader.readuntil(b"\r\n\r\n")
                if len(header) > 16384:
                    raise ValueError("header too large")
                lines = header.decode("latin1").split("\r\n")
                method, target, version = lines[0].split(" ", 2)
                if method == "CONNECT":
                    parsed = urlsplit("https://" + target)
                    port = parsed.port or 443
                    if port != 443:
                        raise ValueError("port blocked")
                else:
                    parsed = urlsplit(target)
                    port = parsed.port or 80
                    if parsed.scheme != "http" or port != 80:
                        raise ValueError("scheme or port blocked")
                host = parsed.hostname
                if not host or parsed.username or parsed.password:
                    raise ValueError("invalid host")
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
                if not addresses or any(
                    not public_ip(info[4][0]) for info in addresses
                ):
                    if len(self.blocked) < 30:
                        self.blocked.append(host[:200])
                    raise ValueError("private address blocked")
                # Numeric IP prevents the connect from resolving the hostname again.
                # Try alternate validated addresses if one network path is unavailable.
                ips = sorted(
                    {info[4][0] for info in addresses}, key=lambda ip: ":" in ip
                )
                for ip in ips[:4]:
                    try:
                        async with asyncio.timeout(4):
                            incoming, upstream = await asyncio.open_connection(ip, port)
                        break
                    except (OSError, asyncio.TimeoutError):
                        continue
                if upstream is None:
                    raise OSError("No validated destination address was reachable")
                if method == "CONNECT":
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                else:
                    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
                    kept = [
                        line
                        for line in lines[1:]
                        if line
                        and not line.lower().startswith(
                            ("proxy-", "connection:", "host:")
                        )
                    ]
                    # Close each HTTP connection so a second absolute request cannot
                    # bypass validation on an already opened upstream connection.
                    authority = host.encode("idna").decode("ascii")
                    upstream.write(
                        (
                            f"{method} {path} {version}\r\nHost: {authority}\r\n"
                            + "\r\n".join(kept)
                            + "\r\nConnection: close\r\n\r\n"
                        ).encode("latin1")
                    )
                    await upstream.drain()
                await writer.drain()

                async def pump(source, destination):
                    total = 0
                    while chunk := await source.read(65536):
                        total += len(chunk)
                        if total > 20 * 1024 * 1024:
                            break
                        destination.write(chunk)
                        await destination.drain()

                pumps = [
                    asyncio.create_task(pump(reader, upstream)),
                    asyncio.create_task(pump(incoming, writer)),
                ]
                try:
                    await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for item in pumps:
                        item.cancel()
                    await asyncio.gather(*pumps, return_exceptions=True)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            if upstream:
                upstream.close()
            writer.close()
            self.tasks.discard(task)


async def scan(url):
    from playwright.async_api import async_playwright

    evidence = {
        "original_url": safe_url(url),
        "redirects": [],
        "requests": [],
        "downloads": [],
        "popups": [],
        "errors": [],
        "loaded": False,
    }
    proxy = PublicProxy()
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0, limit=16384)
    port = server.sockets[0].getsockname()[1]
    screenshot = ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                proxy={"server": f"http://127.0.0.1:{port}", "bypass": "<-loopback>"},
                args=[
                    "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--disable-background-networking",
                    "--disable-extensions",
                ],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=False,
                    service_workers="block",
                    permissions=[],
                )

                async def route_request(route):
                    request = route.request
                    scheme = urlsplit(request.url).scheme
                    if scheme not in ("http", "https") or request.method not in (
                        "GET",
                        "HEAD",
                    ):
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", route_request)
                await context.route_web_socket("**/*", lambda ws: ws.close())
                page = await context.new_page()
                page.on("dialog", lambda dialog: dialog.dismiss())

                async def popup(new_page):
                    if len(evidence["popups"]) < 10:
                        evidence["popups"].append(safe_url(new_page.url))
                    await new_page.close()

                page.on("popup", popup)

                async def download(item):
                    if len(evidence["downloads"]) < 10:
                        evidence["downloads"].append(safe_url(item.url))
                    await item.cancel()

                page.on("download", download)

                def on_request(request):
                    if len(evidence["requests"]) < 100:
                        evidence["requests"].append(
                            {
                                "url": safe_url(request.url),
                                "type": request.resource_type,
                                "method": request.method,
                            }
                        )

                def on_response(response):
                    if (
                        response.request.is_navigation_request()
                        and response.request.frame == page.main_frame
                        and len(evidence["redirects"]) < 20
                    ):
                        evidence["status"] = response.status
                        evidence["redirects"].append(
                            {"url": safe_url(response.url), "status": response.status}
                        )

                page.on("request", on_request)
                page.on("response", on_response)
                await navigate(page, url, evidence)
                content, seconds = await settle_page(page)
                evidence["observation_seconds"] = seconds
                evidence["final_url"] = safe_url(page.url)
                evidence["loaded"] = (
                    urlsplit(page.url).scheme in ("http", "https")
                    and isinstance(evidence.get("status"), int)
                    and 200 <= evidence["status"] < 300
                )
                evidence["content_captured"] = content is not None
                if content is not None:
                    evidence.update(content)
                    for form in evidence.get("forms", []):
                        form["action"] = safe_url(form["action"])
                    evidence["frames"] = [
                        safe_url(x) for x in evidence.get("frames", [])
                    ]
                else:
                    evidence["errors"].append(
                        "Visible page content could not be captured."
                    )
                try:
                    screenshot = base64.b64encode(
                        await page.screenshot(
                            type="jpeg",
                            quality=45,
                            timeout=10000,
                            animations="disabled",
                        )
                    ).decode()
                except Exception:
                    evidence["errors"].append(
                        "Screenshot could not be captured; text evidence was retained."
                    )
                evidence["screenshot_captured"] = bool(screenshot)
                evidence["challenge"] = detect_challenge(
                    evidence.get("title", ""), evidence.get("text", "")
                )
                evidence["content_empty"] = (
                    content is not None
                    and not evidence.get("text", "").strip()
                    and not evidence.get("forms")
                    and not evidence.get("frames")
                )
                evidence["blocked_hosts"] = proxy.blocked
                evidence["coverage"] = (
                    f"One page, anonymous browser, {seconds}-second readiness observation; "
                    "no forms submitted, no login, no files executed. Embedded frames are not inspected in depth."
                )
                await context.close()
            finally:
                await browser.close()
    finally:
        server.close()
        await server.wait_closed()
        tasks = list(proxy.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"evidence": evidence, "screenshot": screenshot}


async def main():
    url = json.loads(sys.stdin.read(8192))["url"]
    async with asyncio.timeout(90):
        result = await scan(url)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
