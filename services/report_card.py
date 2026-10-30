"""Render report gauges locally with Pillow. Call render_score_card via to_thread."""

from __future__ import annotations

import io
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT, SCALE = 1200, 420, 2
PALETTE = {
    "Low risk": "#55d6a0",
    "Suspicious": "#f3bb58",
    "High risk": "#ff747d",
    "Inconclusive": "#a8b5cb",
}


@lru_cache(maxsize=24)
def font(size, bold=False):
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default(size=size * SCALE)


def score_color(value):
    stops = ((0, (85, 214, 160)), (45, (243, 187, 88)), (100, (255, 116, 125)))
    for (left, a), (right, b) in zip(stops, stops[1:]):
        if value <= right:
            t = max(0, (value - left) / (right - left))
            return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    return stops[-1][1]


def render_score_card(report):
    """Return a PNG; no network calls, AI image generation, or disk writes."""
    score = max(0, min(100, int(report["score"])))
    verdict = report["verdict"]
    unknown = verdict == "Inconclusive"
    accent = PALETTE.get(verdict, PALETTE["Inconclusive"])
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "#10151f")
    draw = ImageDraw.Draw(image)

    def box(bounds, **kwargs):
        draw.rounded_rectangle(
            tuple(round(x * SCALE) for x in bounds), radius=24 * SCALE, **kwargs
        )

    def text(x, y, value, size, fill="#f1f5fb", bold=False, anchor="la"):
        draw.text(
            (x * SCALE, y * SCALE),
            value,
            font=font(size, bold),
            fill=fill,
            anchor=anchor,
        )

    box(
        (1, 1, WIDTH - 2, HEIGHT - 2),
        fill="#171f2c",
        outline="#2c374a",
        width=2 * SCALE,
    )
    draw.line(
        (460 * SCALE, 48 * SCALE, 460 * SCALE, 366 * SCALE), fill="#303b4c", width=SCALE
    )
    text(225, 36, "OBSERVED-SIGNAL SCORE", 17, "#a8b5cb", anchor="ma")
    cx, cy, radius, thickness = 225, 213, 132, 22
    bounds = tuple(
        v * SCALE for v in (cx - radius, cy - radius, cx + radius, cy + radius)
    )
    draw.arc(bounds, 135, 405, fill="#354154", width=thickness * SCALE)
    if not unknown:
        for step in range(max(1, score * 3)):
            position = step / 3
            angle = 135 + position * 2.7
            draw.arc(
                bounds,
                angle,
                angle + 1.2,
                fill=score_color(position),
                width=thickness * SCALE,
            )
        angle = math.radians(135 + score * 2.7)
        marker_radius = radius - thickness / 2
        x, y = cx + marker_radius * math.cos(angle), cy + marker_radius * math.sin(
            angle
        )
        draw.ellipse(
            ((x - 6) * SCALE, (y - 6) * SCALE, (x + 6) * SCALE, (y + 6) * SCALE),
            fill="#f1f5fb",
        )
    text(cx, 143, "--" if unknown else str(score), 88, accent, bold=True, anchor="ma")
    text(cx, 248, "NOT RATED" if unknown else "OUT OF 100", 18, "#a8b5cb", anchor="ma")
    text(113, 321, "0", 17, "#8190a6", anchor="ma")
    text(337, 321, "100", 17, "#8190a6", anchor="ma")
    text(cx, 355, "Lower score = fewer observed signals", 15, "#8190a6", anchor="ma")

    text(510, 52, "LINK RISK ASSESSMENT", 17, "#a8b5cb")
    text(508, 91, verdict, 56, accent, bold=True)
    subtitles = {
        "Low risk": "No strong warning signals observed",
        "Suspicious": "Warning signals need a closer look",
        "High risk": "Treat this link with caution",
        "Inconclusive": "Not enough evidence for a verdict",
    }
    text(510, 171, subtitles.get(verdict, ""), 22, "#d4deec")
    confidence = str(report.get("ai", {}).get("confidence", "low")).title()
    limited = (
        report.get("coverage_incomplete")
        or report.get("inspection_status") == "limited"
    )
    text(510, 233, "ANALYSIS CONFIDENCE", 15, "#8190a6")
    text(510, 259, confidence, 25, "#e0e7f1", bold=True)
    text(860, 233, "BROWSER COVERAGE", 15, "#8190a6")
    text(860, 259, "Limited" if limited else "Captured", 25, "#e0e7f1", bold=True)
    if unknown:
        text(
            510,
            324,
            f"Observed signals: {score}/100. This does not establish safety.",
            17,
            "#a8b5cb",
        )
    else:
        text(
            510,
            324,
            "Observed signals and AI verdict are assessed separately.",
            17,
            "#a8b5cb",
        )
    text(510, 355, "A risk rating, not a guarantee of safety.", 16, "#8190a6")
    model = str(report.get("model") or "unavailable")[:80]
    text(WIDTH - 30, 387, f"Model: {model}", 13, "#8190a6", anchor="ra")
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
