"""Answer-level evaluation of the send/hold gate (calls the OpenAI API once per case).

Run from the project root:
    python -m evaluation.run_eval

Each case goes through the real prompt (all of about_me.md in context) and
the same rule verify() uses: send only if the reply is grounded and doesn't
need the owner. expect=send means the knowledge base can answer it; expect=hold
means it can't (private facts, decisions only the owner can make).
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.llm import chat_completion  # noqa: E402

lines = Path(__file__).with_name("cases.jsonl").read_text(encoding="utf-8").splitlines()
cases = [json.loads(line) for line in lines if line.strip()]

wrong_sends, wrong_holds = [], []
for case in cases:
    result = chat_completion(case["text"])
    sent = bool(result["reply"]) and result["grounded"] and not result["needs_owner"]
    got = "send" if sent else "hold"
    mark = "ok" if got == case["expect"] else "XX"
    print(
        f"{mark} expect={case['expect']:<4} got={got:<4} "
        f"grounded={result['grounded']!s:<5} needs_owner={result['needs_owner']!s:<5} "
        f"| {case['text']}  ->  {result['reply']}"
    )
    if got != case["expect"]:
        (wrong_sends if got == "send" else wrong_holds).append(case["text"])

n = len(cases)
print(f"\naccuracy: {1 - (len(wrong_sends) + len(wrong_holds)) / n:.0%} over {n} cases")
print(f"wrong sends (replied when it should have held, the dangerous kind): {len(wrong_sends)}")
print(f"wrong holds (held when it could have replied, just annoying): {len(wrong_holds)}")