"""Turn a results file into tables. Every rate is reported with a 95% Wilson interval."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from .attacks import REALISTIC_STYLES
from .scoring import LEVELS, SUCCESS_LEVELS

Z = 1.959964


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + Z * Z / n
    c = p + Z * Z / (2 * n)
    m = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float, float]:
    """Difference p1 - p2 with a Newcombe hybrid 95% interval."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    return (d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _rate(rows: list[dict], key: str) -> dict:
    scored = [r for r in rows if r.get(key) is not None]
    k, n = sum(bool(r[key]) for r in scored), len(scored)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None, "lo": lo, "hi": hi}


def _fmt(s: dict) -> str:
    if not s["n"]:
        return "no data"
    return f"{s['rate']:.1%} ({s['lo']:.1%} to {s['hi']:.1%}), {s['k']}/{s['n']}"


def summarize(rows: list[dict]) -> dict:
    for r in rows:
        r.setdefault("task", "lookup")
    _derive_levels(rows)
    ok = [r for r in rows if not r.get("api_error")]
    atk = [r for r in ok if r.get("goal")]
    ctl = [r for r in ok if not r.get("goal")]
    def by(keys, data, metric):
        g = defaultdict(list)
        for r in data:
            g[tuple(r[k] for k in keys)].append(r)
        return {" / ".join(k): _rate(v, metric) for k, v in sorted(g.items())}
    diffs = {}
    for model in sorted({r["model"] for r in atk}):
        base = _rate([r for r in atk if r["model"] == model and r["defense"] == "none"], "attack_success")
        for d in sorted({r["defense"] for r in atk} - {"none"}):
            cur = _rate([r for r in atk if r["model"] == model and r["defense"] == d], "attack_success")
            if base["n"] and cur["n"]:
                est, lo, hi = newcombe(cur["k"], cur["n"], base["k"], base["n"])
                diffs[f"{model} / {d} vs none"] = {"diff": est, "lo": lo, "hi": hi}
    false_info = [r for r in atk if r["goal"] == "misinfo" and r["style"] in REALISTIC_STYLES]
    levels = {}
    for r in false_info:
        if r.get("level"):
            levels.setdefault(f"{r['model']} / {r['defense']}", dict.fromkeys(LEVELS, 0))[r["level"]] += 1
    return {
        "false_info_levels": dict(sorted(levels.items())),
        "false_info_broad": by(["model", "defense"], false_info, "attack_success"),
        "false_info_strict": by(["model", "defense"], false_info, "accepted_strict"),
        "providers": sorted({r["provider"] for r in rows}), "seeds": sorted({r["seed"] for r in rows}),
        "trials": len(rows), "api_errors": len(rows) - len(ok), "needs_review": sum(1 for r in ok if r.get("needs_review")),
        "attack_by_model_defense": by(["model", "defense"], atk, "attack_success"),
        "attack_by_model_goal": by(["model", "goal"], atk, "attack_success"),
        "attack_by_model_task_goal": by(["model", "task", "goal"], atk, "attack_success"),
        "attack_by_model_style": by(["model", "style"], atk, "attack_success"),
        "attack_by_model_placement": by(["model", "placement"], atk, "attack_success"),
        "flagged_by_model_defense": by(["model", "defense"], atk, "flagged"),
        "task_under_attack": by(["model", "defense"], atk, "task_correct"),
        "task_control": by(["model", "defense"], ctl, "task_correct"),
        "false_flags_control": by(["model", "defense"], ctl, "flagged"),
        "defense_vs_none": diffs,
    }


TABLES = [("Primary: false number passed on or accepted, realistic payloads", "false_info_broad"),
          ("False number accepted as correct, realistic payloads", "false_info_strict"),
          ("Attack success by model and defense", "attack_by_model_defense"),
          ("Attack success by model and goal", "attack_by_model_goal"),
          ("Attack success by model, task and goal", "attack_by_model_task_goal"),
          ("Attack success by model and payload style", "attack_by_model_style"),
          ("Attack success by model and payload placement", "attack_by_model_placement"),
          ("Injection flagged to the user, attack trials", "flagged_by_model_defense"),
          ("Correct answer given, attack trials", "task_under_attack"),
          ("Correct answer given, no attack", "task_control"),
          ("False alarms, no attack", "false_flags_control")]


def to_markdown(s: dict) -> str:
    lines = ["# Results", ""]
    if "mock" in s["providers"]:
        lines += ["> **SELF-TEST ONLY.** These rows come from the scripted mock client. They test this harness and say nothing about any real model.", ""]
    summary = (f"Trials: {s['trials']}. API errors and truncated replies, excluded from every rate: {s['api_errors']}. "
               f"Awaiting human review, excluded from attack rates until adjudicated: {s['needs_review']}. Seeds: {s['seeds']}.")
    lines += [summary, ""]
    for title, key in TABLES:
        lines += [f"## {title}", "", "| Condition | Rate (95% CI), count |", "|---|---|"]
        lines += [f"| {k} | {_fmt(v)} |" for k, v in s[key].items()] + [""]
    lines += ["## Coded response to false data, realistic payloads", "", "| Condition | " + " | ".join(LEVELS) + " |", "|---|---|---|---|---|"]
    lines += [f"| {k} | " + " | ".join(str(v[x]) for x in LEVELS) + " |" for k, v in s["false_info_levels"].items()] + [""]
    lines += ["## Change in attack success compared with no defense", "", "| Comparison | Difference (95% CI) |", "|---|---|"]
    lines += [f"| {k} | {v['diff']:+.1%} ({v['lo']:+.1%} to {v['hi']:+.1%}) |" for k, v in s["defense_vs_none"].items()] + [""]
    lines += ["Trials inside one condition share a fixed attack template, so treat these intervals as a lower bound on uncertainty.", ""]
    return "\n".join(lines)


def review_id(trial_id: str) -> str:
    """An opaque ID, so the coder can't see which condition produced a reply."""
    return hashlib.sha256(trial_id.encode()).hexdigest()[:12]


def apply_review(rows: list[dict], levels: dict[str, str]) -> list[dict]:
    """Apply human codes (review ID to level) to replies that were queued for review."""
    for r in rows:
        level = levels.get(review_id(r["trial_id"]))
        if level and r.get("needs_review"):
            r["level"], r["attack_success"], r["needs_review"], r["reviewed"] = level, level in SUCCESS_LEVELS, False, True
    return rows


def _derive_levels(rows: list[dict]) -> None:
    for r in rows:
        if r.get("goal") and "level" not in r and not r.get("needs_review") and r.get("attack_success") is not None:
            r["level"] = "endorsed" if r["attack_success"] else "rejected"
        r["accepted_strict"] = None if r.get("level") is None else r["level"] == "endorsed"
