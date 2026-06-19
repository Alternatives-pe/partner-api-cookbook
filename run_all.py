"""
Smoke-test runner — execute every cookbook recipe with a light, known-good
invocation and report pass/fail. Handy for checking that all examples still work
against the live API (e.g. after an API change or before publishing).

Usage:
    python run_all.py            # run them all (CSV output discarded)
    python run_all.py --json     # same, but exercise the JSON formatter
    python run_all.py --show     # also print each script's data output

Exits non-zero if any recipe fails. Needs a valid ALT_API_KEY in .env.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# A representative, deliberately small invocation for each recipe.
RECIPES = [
    ("enrich_company",       ["shopback", "-n", "1"]),
    ("sourcing_raising_now", ["--country", "SGP", "-n", "5"]),
    ("investor_portfolio",   ["Wavemaker", "-n", "5"]),
    ("person_background",    ["Shanru Lai", "-n", "5"]),
    ("market_map",           ["--themes", "themes_payments", "--country", "SGP", "-n", "5"]),
    ("captable",             ["shopback", "-n", "5"]),
    ("fund_benchmark",       ["--vintage-from", "2016", "--vintage-to", "2017", "-n", "3"]),
    ("syndicate_map",        ["--themes", "themes_payments", "--companies", "20", "-n", "5"]),
    ("pe_screener",          ["--min-revenue", "25000000", "--country", "SGP", "-n", "5"]),
    ("watchlist_monitor",    ["c16a0ffd-4dbb-4f7b-a9ca-a3a47f93be67"]),
    ("lp_intelligence",      ["--lp", "Wavemaker", "-n", "5"]),
    ("service_providers",    ["--search", "Deloitte", "-n", "5"]),
    ("reference_data",       ["--categories", "themes", "-n", "5"]),
]


def main():
    parser = argparse.ArgumentParser(description="Run every cookbook recipe as a smoke test.")
    parser.add_argument("--json", action="store_true", help="run each recipe with --format json")
    parser.add_argument("--show", action="store_true", help="print each recipe's data output too")
    parser.add_argument("--timeout", type=int, default=180, help="per-recipe timeout in seconds")
    args = parser.parse_args()

    results = []
    print(f"Running {len(RECIPES)} recipes…\n")
    for name, recipe_args in RECIPES:
        cmd = [PY, str(ROOT / "examples" / f"{name}.py"), *recipe_args]
        if args.json:
            cmd += ["--format", "json"]
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                  timeout=args.timeout)
            ok = proc.returncode == 0
            note = ""
            if ok:
                # Scripts print a one-line summary to stderr; show the last line.
                lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
                note = lines[-1] if lines else ""
            else:
                note = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[-1:] or [""]
                note = note[0]
        except subprocess.TimeoutExpired:
            ok, note, proc = False, f"timed out after {args.timeout}s", None
        elapsed = time.monotonic() - start

        results.append((name, ok))
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        print(f" {mark} {name:<22} {elapsed:5.1f}s  {note}")
        if not ok and proc is not None:
            sys.stderr.write("   ---- command ----\n   " + " ".join(cmd) + "\n")
            sys.stderr.write(_indent(proc.stdout, "   out| "))
            sys.stderr.write(_indent(proc.stderr, "   err| "))
        elif args.show and proc is not None:
            sys.stdout.write(_indent(proc.stdout, "   | "))

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} recipes passed.")
    sys.exit(0 if passed == total else 1)


def _indent(text, prefix):
    if not text:
        return ""
    return "".join(prefix + ln + "\n" for ln in text.rstrip().splitlines())


if __name__ == "__main__":
    main()
