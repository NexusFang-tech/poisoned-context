"""Command line for the study."""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from . import report, runner, scoring
from .clients import AnthropicClient, MockClient
from .defenses import DEFENSES


def _review_path(results: Path) -> Path:
    return results.with_suffix(".review.csv")


def _read_levels(path: Path) -> dict[str, str]:
    """Read coded levels. Tolerates the byte-order mark and encoding Excel can add when saving."""
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        return {x["review_id"].strip(): x["level"].strip().lower() for x in csv.DictReader(fh)
                if x["level"].strip().lower() in scoring.LEVELS}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="poisoned-context", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run or resume a study")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--provider", choices=["anthropic", "mock"], default="anthropic")
    r.add_argument("--trials", type=int, default=10, help="repeats per realistic attack condition")
    r.add_argument("--simple-trials", type=int, help="repeats per command-style attack condition (default: same as --trials)")
    r.add_argument("--control-trials", type=int, default=30, help="no-attack repeats per defense")
    r.add_argument("--defenses", nargs="+", choices=DEFENSES, default=list(DEFENSES))
    r.add_argument("--seed", type=int, default=20261103)
    r.add_argument("--out", type=Path, default=Path("results/run.jsonl"))
    r.add_argument("--max-requests", type=int, default=50, help="stop before spending more than this many requests")
    r.add_argument("--dry-run", action="store_true", help="show the plan and estimated tokens, and send nothing")
    r.add_argument("--input-price", type=float, help="your model's input price, USD per million tokens")
    r.add_argument("--output-price", type=float, help="your model's output price, USD per million tokens")
    p = sub.add_parser("report", help="write report.md and summary.json")
    p.add_argument("results", type=Path)
    p.add_argument("--out-dir", type=Path)
    q = sub.add_parser("review", help="export replies that need a human decision")
    q.add_argument("results", type=Path)
    x = sub.add_parser("rescore", help="re-apply the scorer to saved replies without any API calls")
    x.add_argument("results", type=Path)
    x.add_argument("--out", type=Path, required=True)
    g = sub.add_parser("agreement", help="compare two coders' review files")
    g.add_argument("first", type=Path)
    g.add_argument("second", type=Path)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        trials = runner.plan(a.models, a.trials, a.control_trials, tuple(a.defenses), a.simple_trials)
        pending = len(trials) - len(runner.completed_ids(a.out) & {t.id for t in trials})
        tin, tout = runner.estimate_tokens(trials, a.seed)
        print(f"Planned trials: {len(trials)}. Still to run: {pending}.")
        print(f"Estimated full-run tokens: about {tin:,} input and {tout:,} output.")
        if a.input_price is not None and a.output_price is not None:
            print(f"Estimated full-run cost: about ${tin / 1e6 * a.input_price + tout / 1e6 * a.output_price:,.2f}, before retries.")
        if a.dry_run:
            print("Dry run. Nothing was sent.")
            return 0
        client = MockClient() if a.provider == "mock" else AnthropicClient()
        if a.provider == "mock":
            print("MOCK CLIENT: this tests the harness and doesn't measure a model.")
        def progress(i, n, st):
            if i % 25 == 0 or i == n:
                print(f"{i}/{n} done, {st['api_errors']} API errors", flush=True)
        st = runner.run(trials, client, a.out, a.seed, a.max_requests, progress)
        print(json.dumps(st))
    elif a.cmd == "agreement":
        out = report.agreement(_read_levels(a.first), _read_levels(a.second))
        print(f"Rows coded by both: {out['n']}")
        print(f"All four levels: {out['levels']['agreement']:.1%} agreement, kappa {out['levels']['kappa']:.2f}")
        print(f"Success or not: {out['success']['agreement']:.1%} agreement, kappa {out['success']['kappa']:.2f}")
        print("Disagreements:", ", ".join(out["disagreements"]) or "none")
    elif a.cmd == "rescore":
        rows = runner.rescore_rows(report.load(a.results))
        a.out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"Rescored {len(rows)} rows into {a.out}. Replies awaiting review: {sum(1 for r in rows if r.get('needs_review'))}.")
    elif a.cmd == "review":
        rows = [r for r in report.load(a.results) if r.get("needs_review")]
        random.Random(0).shuffle(rows)  # hides any pattern from run order
        path = _review_path(a.results)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["review_id", "goal", "text", "suggested_level", "level"])
            w.writerows([report.review_id(r["trial_id"]), r["goal"], r["text"], scoring.suggest_level(r["text"]), ""] for r in rows)
        print(f"{len(rows)} replies written to {path}. Conditions are hidden. Fill in the level column, then run report.")
    else:
        rows = report.load(a.results)
        path = _review_path(a.results)
        if path.exists():
            rows = report.apply_review(rows, _read_levels(path))
        s = report.summarize(rows)
        out = a.out_dir or a.results.parent
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
        (out / "report.md").write_text(report.to_markdown(s), encoding="utf-8")
        print(f"Wrote {out / 'report.md'} and {out / 'summary.json'}. Replies awaiting review: {s['needs_review']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
