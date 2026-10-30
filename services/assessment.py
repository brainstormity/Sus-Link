"""Combine observed signals, inspection coverage, and the AI assessment."""

LABELS = {
    "low_risk": "Low risk",
    "suspicious": "Suspicious",
    "high_risk": "High risk",
    "inconclusive": "Inconclusive",
}
RANK = {"Low risk": 0, "Suspicious": 1, "High risk": 2}
SCORE_BANDS = {"low_risk": (0, 24), "suspicious": (25, 59), "high_risk": (60, 100)}


def verdict_for_score(score):
    return "High risk" if score >= 60 else "Suspicious" if score >= 25 else "Low risk"


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
    rule_score = rules["score"]
    score = None
    if verdict != "Inconclusive":
        ai_score = 0
        if model and ai["assessment"] in SCORE_BANDS:
            floor, ceiling = SCORE_BANDS[ai["assessment"]]
            # Normalize defensively for legacy assessments; current API responses
            # are validated against these same bands before reaching this point.
            ai_score = max(floor, min(ceiling, int(ai.get("risk_score", floor))))
        score = max(rule_score, ai_score)
        verdict = verdict_for_score(score)
    return {
        **rules,
        "score": score,
        "rule_score": rule_score,
        "scoring": "Overall risk v1: higher of AI assessment and observed-rule score; 0–24 low, 25–59 suspicious, 60–100 high. Not a probability.",
        "verdict": verdict,
        "ai": ai,
        "assessment_reasons": list(dict.fromkeys(reasons)),
        "inspection_status": "limited" if rules["coverage_incomplete"] else "complete",
    }
