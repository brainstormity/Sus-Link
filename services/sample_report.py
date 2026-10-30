"""Fictional report fixtures and local graphics; no service calls or database writes."""

from datetime import datetime, timezone
import io
from types import SimpleNamespace

from PIL import Image, ImageDraw

from services.report_card import font, render_score_card

SAMPLES = {
    "low_risk": (
        "Low risk",
        12,
        "No strong threat indicators were identified on this fictional informational page.",
    ),
    "suspicious": (
        "Suspicious",
        42,
        "This fictional page asks visitors to verify account details using an unfamiliar form.",
    ),
    "high_risk": (
        "High risk",
        87,
        "This fictional page imitates an account verification flow and requests sensitive information.",
    ),
    "inconclusive": (
        "Inconclusive",
        None,
        "The fictional destination displayed an access challenge, preventing a complete assessment.",
    ),
}


def sample_scan(kind):
    verdict, score, summary = SAMPLES[kind]
    limited = kind == "inconclusive"
    findings = (
        []
        if kind in ("low_risk", "inconclusive")
        else [
            {
                "finding": "The page requests account details through a verification form.",
                "points": 10,
            }
        ]
    )
    report = {
        "verdict": verdict,
        "score": score,
        "rule_score": 10 if findings else 0,
        "findings": findings,
        "coverage_incomplete": limited,
        "inspection_status": "limited" if limited else "complete",
        "assessment_reasons": (
            ["An access challenge prevented inspection of the intended page."]
            if limited
            else []
        ),
        "ai": {
            "summary": summary,
            "recommendation": (
                "Do not submit sensitive information. Verify the destination independently."
                if kind in ("high_risk", "suspicious")
                else "Review the destination before sharing information."
            ),
            "confidence": "low" if limited else "medium",
            "assessment": kind,
            "risk_score": score if score is not None else 0,
            "findings": (
                ["The verification wording creates urgency around an account action."]
                if findings
                else []
            ),
            "limitations": ["This is fictional sample data; no website was scanned."],
        },
    }
    return SimpleNamespace(
        report=report,
        model="sample-model",
        evidence={},
        created_at=datetime.now(timezone.utc),
    )


def render_sample_assets(report):
    """Run in a worker thread, just like live report rendering."""
    card = render_score_card(
        {**report, "model": "sample-model", "domain": "example.test"}
    )
    picture = Image.new("RGB", (1280, 800), "#f5f7fa")
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, 0, 1280, 80), fill="#e4e9f0")
    draw.rounded_rectangle((130, 18, 1150, 61), radius=12, fill="white")
    draw.text((155, 23), "https://example.test/preview", fill="#586477", font=font(12))
    draw.text((100, 128), "EXAMPLE PAGE", fill="#263753", font=font(14, True))
    draw.text(
        (100, 181), "SAMPLE PREVIEW - no website visited", fill="#718099", font=font(10)
    )
    draw.rounded_rectangle(
        (100, 250, 1180, 684), radius=22, fill="white", outline="#dde3ed", width=2
    )
    if report["verdict"] == "Inconclusive":
        title, description = (
            "Verify you are human",
            "A fictional access challenge for testing inspection limits.",
        )
    elif report["verdict"] == "Low risk":
        title, description = (
            "Welcome to Example",
            "A fictional information page for testing the report layout.",
        )
    else:
        title, description = (
            "Verify your account",
            "A fictional account form for testing security findings.",
        )
    draw.text((150, 292), title, fill="#18263d", font=font(22, True))
    draw.text((150, 365), description, fill="#69778c", font=font(11))
    draw.rounded_rectangle(
        (150, 440, 1125, 503), radius=9, fill="#f6f8fb", outline="#dde3ed", width=2
    )
    draw.text(
        (175, 454), "Example field - disabled preview", fill="#8b96a8", font=font(12)
    )
    draw.rounded_rectangle((150, 550, 440, 611), radius=10, fill="#536ce8")
    draw.text((180, 562), "Preview only", fill="white", font=font(13, True))
    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=80)
    return card, output.getvalue()
