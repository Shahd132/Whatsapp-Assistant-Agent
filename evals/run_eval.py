"""Measure how reliably the assistant decides what to send and what to hold.

    python -m evals.run_eval             # one run per case
    python -m evals.run_eval --runs 3    # a case passes only if all 3 runs pass

Needs OPENAI_API_KEY and OPENAI_MODEL in .env. Costs a few cents. Exit code 1 if
anything that should have been held was sent ("unsafe send"), so CI can gate on it.

The decision under test is the same one verify() makes in app/agent_graph.py:
send only if there is a reply, it is grounded, and it does not need the owner.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from app.llm import chat_completion, clean_reply   # noqa: E402

CAIRO = ZoneInfo("Africa/Cairo")
PUNCTUATION = re.compile(r"[.,،!;:]")  # the persona forbids these


def run_case(case: dict) -> dict:
    now = datetime.fromisoformat(case["now"]).replace(tzinfo=CAIRO) if case.get("now") else None
    out = chat_completion(case["message"], [], "text", None, now=now)
    action = "send" if out["reply"] and out["grounded"] and not out["needs_owner"] else "hold"

    problems = []
    if case["expect"] in ("send", "hold") and action != case["expect"]:
        problems.append("unsafe_send" if action == "send" else "needless_hold")
    if case.get("forbid_regex") and re.search(case["forbid_regex"], out["reply"]):
        problems.append("forbidden_text")
    return {"action": action, "reply": out["reply"], "problems": problems,
             "style_slip": clean_reply(out["reply"]) != out["reply"].strip()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.jsonl")))
    args = ap.parse_args()

    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    totals, by_cat, failures = defaultdict(int), defaultdict(lambda: [0, 0]), []

    for case in cases:
        runs = [run_case(case) for _ in range(args.runs)]
        problems = sorted({p for r in runs for p in r["problems"]})
        passed = not problems
        by_cat[case["category"]][0] += passed
        by_cat[case["category"]][1] += 1
        totals["passed"] += passed
        totals["style_slips"] += any(r["style_slip"] for r in runs)
        for p in problems:
            totals[p] += 1
        if not passed:
            failures.append({"id": case["id"], "expected": case["expect"], "problems": problems,
                             "got": runs[0]["action"], "reply": runs[0]["reply"]})
        print(f"{'PASS' if passed else 'FAIL'}  {case['id']:<10} expected={case['expect']:<5} got={runs[0]['action']}")

    n = len(cases)
    print(f"\n{totals['passed']}/{n} passed ({100 * totals['passed'] / n:.0f}%)  runs/case={args.runs}")
    print(f"unsafe sends (should have been held): {totals['unsafe_send']}")
    print(f"needless holds (could have auto-replied): {totals['needless_hold']}")
    print(f"invented/forbidden text: {totals['forbidden_text']}   punctuation slips: {totals['style_slips']}")
    for cat, (ok, total) in sorted(by_cat.items()):
        print(f"  {cat:<14} {ok}/{total}")

    summary = {"date": datetime.now().isoformat(timespec="seconds"), "cases": n, "runs_per_case": args.runs,
               "passed": totals["passed"], "unsafe_sends": totals["unsafe_send"],
               "needless_holds": totals["needless_hold"], "forbidden_text": totals["forbidden_text"],
               "style_slips": totals["style_slips"], "by_category": dict(by_cat), "failures": failures}
    (Path(__file__).with_name("results.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if totals["unsafe_send"] else 0


if __name__ == "__main__":
    sys.exit(main())
