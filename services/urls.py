import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit


def validate_url(value: str) -> str:
    if len(value) > 4096 or any(ord(c) < 33 for c in value) or "\\" in value:
        raise ValueError("The link is malformed or too long.")
    try:
        p = urlsplit(value)
        if (
            p.scheme.lower() not in ("http", "https")
            or not p.hostname
            or p.username
            or p.password
        ):
            raise ValueError(
                "Only public HTTP or HTTPS links without embedded credentials are supported."
            )
        if p.port not in (None, 80, 443):
            raise ValueError("Only web ports 80 and 443 are supported.")
        host = p.hostname.lower().rstrip(".")
        if (
            host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
            or "." not in host
        ):
            raise ValueError("Local or internal addresses cannot be scanned.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host.encode("idna")
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError("Local or reserved addresses cannot be scanned.")
        return urlunsplit((p.scheme.lower(), p.netloc, p.path or "/", p.query, ""))
    except (UnicodeError, TypeError) as exc:
        raise ValueError("The link has an invalid hostname.") from exc


def extract_urls(message: str) -> list[str]:
    found = []
    for match in re.finditer(r"https?://[^\s<>]+", message, re.I):
        raw = match.group().rstrip(".,!?;")
        # Markdown often leaves closing delimiters attached to links.
        while raw.endswith((")", "]")) and raw.count(raw[-1]) > raw.count(
            {")": "(", "]": "["}[raw[-1]]
        ):
            raw = raw[:-1]
        try:
            url = validate_url(raw)
        except ValueError:
            continue
        if url not in found:
            found.append(url)
    return found[:25]


def redact_url(value: str) -> str:
    try:
        p = urlsplit(value)
        return urlunsplit(
            (p.scheme, p.netloc, p.path, "[redacted]" if p.query else "", "")
        )[:1000]
    except ValueError:
        return "[invalid URL]"
