"""Combine observed signals, inspection coverage, and the AI assessment."""

LABELS = {
    "low_risk": "Low risk",
    "suspicious": "Suspicious",
    "high_risk": "High risk",
    "inconclusive": "Inconclusive",
}
RANK = {"Low risk": 0, "Suspicious": 1, "High risk": 2}


def combine(evidence, rules, ai, model):
    reasons = list(rules.get("coverage_reasons", []))
    if not model:
        reasons.append(
            "AI analysis was unavailable; only observed browser signals could be assessed."
        )
    elif ai["assessment"] == "inconclusive":
        reasons.append(
            "The AI could not reach a supported assessment from the captured evidence."
        )
    # Missing coverage must never hide an observed warning or imply low risk.
    warnings = []
    if rules["score"] >= 25:
        warnings.append("High risk" if rules["score"] >= 60 else "Suspicious")
    ai_verdict = LABELS[ai["assessment"]]
    if model and ai_verdict in ("Suspicious", "High risk"):
        warnings.append(ai_verdict)
    if warnings:
        verdict = max(warnings, key=RANK.get)
    elif reasons or rules["coverage_incomplete"]:
        verdict = "Inconclusive"
    else:
        verdict = "Low risk"
    return {
        **rules,
        "verdict": verdict,
        "ai": ai,
        "assessment_reasons": list(dict.fromkeys(reasons)),
        "inspection_status": "limited" if rules["coverage_incomplete"] else "complete",
    }
