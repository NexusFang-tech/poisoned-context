"""Command line for the study."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from . import report, runner
from .clients import AnthropicClient, MockClient
from .defenses import DEFENSES


def _review_path(results: Path) -> Path:
    return results.with_suffix(".review.csv")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="poisoned-context", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run or resume a study")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--provider", choices=["anthropic", "mock"], default="anthropic")
    r.add_argument("--trials", type=int, default=10, help="repeats per attack condition")
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
    a = ap.parse_args(argv)

    if a.cmd == "run":
        trials = runner.plan(a.models, a.trials, a.control_trials, tuple(a.defenses))
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
    elif a.cmd == "review":
        rows = [r for r in report.load(a.results) if r.get("needs_review")]
        path = _review_path(a.results)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["trial_id", "goal", "outcome", "text", "complied_yes_or_no"])
            w.writerows([r["trial_id"], r["goal"], r["outcome"], r["text"], ""] for r in rows)
        print(f"{len(rows)} replies written to {path}. Fill in the last column, then run report.")
    else:
        rows = report.load(a.results)
        path = _review_path(a.results)
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                decisions = {x["trial_id"]: x["complied_yes_or_no"].strip().lower() == "yes" for x in csv.DictReader(fh)
                             if x["complied_yes_or_no"].strip().lower() in ("yes", "no")}
            rows = report.apply_review(rows, decisions)
        s = report.summarize(rows)
        out = a.out_dir or a.results.parent
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
        (out / "report.md").write_text(report.to_markdown(s), encoding="utf-8")
        print(f"Wrote {out / 'report.md'} and {out / 'summary.json'}. Replies awaiting review: {s['needs_review']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
