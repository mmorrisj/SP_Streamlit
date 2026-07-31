"""CLI entry point for the evaluation harness.

Usage:
    python -m evals.run_eval --list
    python -m evals.run_eval                       # all no-LLM components
    python -m evals.run_eval --components retrieval entity_matching
    python -m evals.run_eval --llm                 # include LLM-gated probes
    python -m evals.run_eval --no-embed            # skip embedding-model loads

Results land in evals/results/ as timestamped .json (full cases) and .md
(human summary).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="SP eval harness")
    parser.add_argument("--components", nargs="*", default=None,
                        help="subset of components to run (default: all)")
    parser.add_argument("--llm", action="store_true",
                        help="enable LLM-dependent probes (costs API calls)")
    parser.add_argument("--no-embed", action="store_true",
                        help="skip probes that require loading the embedding model")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    import evals.components  # noqa: F401  (registers everything)
    from evals.core import runner

    if args.list:
        for name in runner.available():
            print(name)
        return 0

    results = runner.run(args.components, llm=args.llm, embed=not args.no_embed)
    json_path, md_path = runner.write_reports(results, tag=args.tag)

    for r in results:
        status = "ERROR" if r.error else "ok"
        print(f"[{status:5}] {r.component:32} {r.duration_s:8.1f}s "
              f"{len(r.metrics)} metrics, {len(r.cases)} cases")
    print(f"\nJSON: {json_path}\nMD:   {md_path}")
    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
