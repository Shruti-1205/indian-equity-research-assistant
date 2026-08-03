"""Run the labeled benchmark: load benchmark/labels.csv, execute the pipeline
on each row, and compute accuracy metrics vs expected labels.

Metrics reported:
  - primary_driver accuracy (exact match)
  - hallucination rate (= % of rows where validation_ok is False)
  - confidence distribution
  - latency stats
  - per-driver confusion matrix

Usage:
  python -m benchmark.build_labels     # one-time, generate/refresh labels
  python -m scripts.benchmark          # run + score
"""
from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

# Back-compat: allow `Path` at module level for the new checkpoint arg default.
from src.agents.graph import run

LABELS_PATH = Path(__file__).resolve().parents[1] / "benchmark" / "labels.csv"
REPORT_PATH = Path(__file__).resolve().parents[1] / "benchmark" / "report.json"
MARKDOWN_PATH = Path(__file__).resolve().parents[1] / "benchmark" / "report.md"


def _load_labels() -> list[dict]:
    if not LABELS_PATH.exists():
        raise SystemExit(
            f"No labels file found at {LABELS_PATH}.\n"
            "Run  `python -m benchmark.build_labels`  first to seed one."
        )
    with LABELS_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _run_case(row: dict) -> dict:
    symbol = row["symbol"]
    date = row["date"]
    expected = (row.get("expected_driver") or "").strip().lower()

    t0 = time.time()
    err = ""
    state = {}
    try:
        state = run(symbol, date, "")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    latency = round(time.time() - t0, 1)

    predicted = (state.get("primary_driver") or "").strip().lower()
    confidence = (state.get("confidence") or "").strip().lower()
    validation_ok = bool(state.get("validation_ok"))
    unverified = state.get("unverified_claims") or []

    match = predicted == expected and expected != ""
    return {
        "symbol": symbol,
        "date": date,
        "expected": expected,
        "predicted": predicted,
        "confidence": confidence,
        "match": match,
        "validation_ok": validation_ok,
        "unverified": unverified,
        "latency_s": latency,
        "error": err,
        "explanation_preview": (state.get("explanation") or "")[:200].replace("\n", " "),
    }


def _print_confusion(results: list[dict]) -> str:
    drivers = ["company", "sector", "unclear"]
    mtx: dict[tuple[str, str], int] = defaultdict(int)
    for r in results:
        mtx[(r["expected"], r["predicted"])] += 1

    lines = []
    header = "expected \\ predicted  " + "".join(f"{d[:8]:>10s}" for d in drivers)
    lines.append(header)
    lines.append("-" * len(header))
    for e in drivers:
        row_cells = "".join(f"{mtx[(e, p)]:>10d}" for p in drivers)
        lines.append(f"{e:22s}{row_cells}")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", type=float, default=13.0,
                    help="Seconds between cases. 13s respects Cerebras 5 req/min limit.")
    ap.add_argument("--checkpoint", type=str,
                    default=str(Path(__file__).resolve().parents[1] / "benchmark" / "progress.json"),
                    help="Checkpoint file; resumes from here if interrupted.")
    args, _ = ap.parse_known_args()

    labels = _load_labels()
    print(f"Loaded {len(labels)} labeled cases. Pacing: {args.pace}s between cases.\n")

    # Load checkpoint if exists
    checkpoint_path = Path(args.checkpoint)
    completed: dict[tuple[str, str], dict] = {}
    if checkpoint_path.exists():
        try:
            saved = json.loads(checkpoint_path.read_text())
            for c in saved:
                completed[(c["symbol"], c["date"])] = c
            print(f"Resumed from checkpoint with {len(completed)} completed cases.\n")
        except Exception:
            pass

    results: list[dict] = []
    for i, row in enumerate(labels, 1):
        key = (row["symbol"], row["date"])
        if key in completed:
            r = completed[key]
            results.append(r)
            print(f"[{i:>3d}/{len(labels)}] cached  {r['symbol']:15s} {r['date']}  "
                  f"expected={r['expected']:8s} predicted={r['predicted']:8s}")
            continue

        r = _run_case(row)
        results.append(r)
        tag = "OK " if r["match"] else ("ERR" if r["error"] else "MIS")
        if r["error"]:
            detail = r["error"][:80]
            print(f"[{i:>3d}/{len(labels)}] {tag} {r['symbol']:15s} {r['date']}  "
                  f"expected={r['expected']:8s}  {detail}  ({r['latency_s']}s)")
        else:
            val = "val_ok" if r["validation_ok"] else f"UNVERIFIED:{r['unverified']}"
            print(f"[{i:>3d}/{len(labels)}] {tag} {r['symbol']:15s} {r['date']}  "
                  f"expected={r['expected']:8s} predicted={r['predicted']:8s}  "
                  f"conf={r['confidence']:6s}  {val}  ({r['latency_s']}s)")

        # Save checkpoint after each case so we can resume if interrupted.
        checkpoint_path.write_text(json.dumps(results, indent=2, default=str))

        # Pace to respect Cerebras 5 req/min free-tier limit.
        if i < len(labels):
            import time as _t
            _t.sleep(args.pace)

    # ── Metrics ──
    total = len(results)
    matches = sum(1 for r in results if r["match"])
    driver_acc = matches / total if total else 0.0
    validation_ok_rate = sum(1 for r in results if r["validation_ok"]) / total if total else 0.0
    hallucination_rate = 1 - validation_ok_rate
    errors = [r for r in results if r["error"]]
    latencies = [r["latency_s"] for r in results if not r["error"]]

    conf_dist = Counter(r["confidence"] for r in results)
    driver_dist = Counter(r["predicted"] for r in results)

    report = {
        "n_cases": total,
        "driver_accuracy": round(driver_acc, 3),
        "validation_ok_rate": round(validation_ok_rate, 3),
        "hallucination_rate": round(hallucination_rate, 3),
        "n_errors": len(errors),
        "confidence_distribution": dict(conf_dist),
        "driver_distribution": dict(driver_dist),
        "latency_s": {
            "mean": round(mean(latencies), 1) if latencies else None,
            "median": round(median(latencies), 1) if latencies else None,
            "min": round(min(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "confusion_matrix": _print_confusion(results),
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))

    print("\n" + "=" * 72)
    print("BENCHMARK RESULTS")
    print("=" * 72)
    print(f"  primary_driver accuracy   {driver_acc*100:5.1f}%   ({matches}/{total})")
    print(f"  validation pass rate      {validation_ok_rate*100:5.1f}%   ({sum(1 for r in results if r['validation_ok'])}/{total})")
    print(f"  hallucination rate        {hallucination_rate*100:5.1f}%")
    print(f"  errors                    {len(errors)}")
    print(f"  latency (s)               mean {report['latency_s']['mean']}  median {report['latency_s']['median']}  max {report['latency_s']['max']}")
    print(f"  confidence distribution   {dict(conf_dist)}")
    print(f"  driver distribution       {dict(driver_dist)}")
    print("\nConfusion matrix:")
    print(report["confusion_matrix"])

    # ── Markdown report for the README ──
    md = [
        "# Benchmark report\n",
        f"Run on **{time.strftime('%Y-%m-%d')}** against `benchmark/labels.csv`.\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases | {total} |",
        f"| Primary-driver accuracy | **{driver_acc*100:.1f}%** |",
        f"| Numeric-grounding pass rate | **{validation_ok_rate*100:.1f}%** |",
        f"| Hallucination rate | **{hallucination_rate*100:.1f}%** |",
        f"| Errors | {len(errors)} |",
        f"| Latency (mean) | {report['latency_s']['mean']}s |",
        f"| Latency (p50) | {report['latency_s']['median']}s |",
        "",
        "## Per-case results",
        "",
        "| Symbol | Date | Expected | Predicted | Match | Conf | Val OK | Latency |",
        "|---|---|---|---|:---:|---|:---:|---|",
    ]
    for r in results:
        md.append(
            f"| {r['symbol']} | {r['date']} | {r['expected']} | {r['predicted']} "
            f"| {'✅' if r['match'] else '❌'} | {r['confidence']} "
            f"| {'✅' if r['validation_ok'] else '❌'} | {r['latency_s']}s |"
        )
    md.extend([
        "",
        "## Confusion matrix",
        "",
        "```",
        report["confusion_matrix"],
        "```",
        "",
        "## Methodology note",
        "",
        "Labels in `benchmark/labels.csv` are produced by an independent LLM judge. "
        "`benchmark/build_candidates.py` assembles one row per (symbol, date) case "
        "containing every signal the synthesis agent sees; that file is handed to "
        "Claude Opus, which assigns the ground-truth driver. The judge is a strictly "
        "stronger model than the one being scored, which mitigates self-preference "
        "bias (Zheng et al., NeurIPS 2023). For rigorous evaluation these labels "
        "should still be hand-reviewed by a domain expert — the `note` column is "
        "provided for that purpose.",
        "",
        "The **hallucination rate** metric is independent of label quality: it "
        "measures whether every numeric claim in the synthesis output appears "
        "verbatim in the source data, regardless of whether the classification "
        "is correct.",
    ])
    MARKDOWN_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\nSaved JSON report  → {REPORT_PATH}")
    print(f"Saved Markdown     → {MARKDOWN_PATH}")


if __name__ == "__main__":
    main()
