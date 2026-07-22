"""Tier 2: curated live end-to-end against the running server (full pipeline + real CT.gov).

25 hand-picked questions spanning every intent, all refusal paths, and unsupported capabilities.
Records status, viz type / refuse reason, matched count, and latency. Sequential to be gentle on
the public API.
"""

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"

# (question, expected_status)  expected in {ok, refused, needs_clarification}
CASES = [
    ("How are melanoma trials distributed across phases?", "ok"),
    ("What's the status breakdown of breast cancer trials?", "ok"),
    ("Most common intervention types for pancreatic cancer trials?", "ok"),
    ("How has the number of Pembrolizumab trials changed per year since 2018?", "ok"),
    ("How many ALS trials started each year?", "ok"),
    ("Compare the phase distribution of Nivolumab vs Pembrolizumab trials.", "ok"),
    ("Compare trial status between Keytruda and Opdivo.", "ok"),
    ("Which countries have the most recruiting glioblastoma trials?", "ok"),
    ("Where are multiple sclerosis trials being run?", "ok"),
    ("Show a network of sponsors and drugs for melanoma trials.", "ok"),
    ("Which drugs co-occur in lung cancer combination studies?", "ok"),
    # too-broad -> refused downstream by count()
    ("Show the phase distribution of all clinical trials.", "refused"),
    ("Break down every clinical trial by status.", "refused"),
    # out-of-domain -> refused by planner
    ("What's the best pizza in New York?", "refused"),
    ("Who won the World Cup in 2022?", "refused"),
    # ambiguous -> clarification (or refuse)
    ("trials for it", "needs_clarification"),
    ("compare them", "needs_clarification"),
    # unsupported capabilities -> should refuse (the end-to-end acid test)
    ("What was the overall survival rate for Keytruda in melanoma trials?", "refused"),
    ("What's the average enrollment size for NSCLC phase 3 trials?", "refused"),
    ("What are the inclusion criteria for ALS trials?", "refused"),
    ("What adverse events were reported for Durvalumab?", "refused"),
    ("Which investigators run the most breast cancer trials?", "refused"),
    ("How long do phase 3 melanoma trials typically take?", "refused"),
    ("Tell me about trial NCT04280705.", "refused"),
    ("What's the phase distribution of Semaglutide trials?", "ok"),
]


def main() -> None:
    out = sys.argv[1]
    try:
        httpx.get(f"{BASE}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"server not reachable at {BASE}: {e}", file=sys.stderr)
        sys.exit(1)

    results = []
    with httpx.Client(timeout=120) as c:
        for i, (q, expected) in enumerate(CASES):
            t = time.perf_counter()
            try:
                r = c.post(f"{BASE}/visualize", json={"query": q})
                body = r.json()
            except Exception as e:
                body = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            dt = time.perf_counter() - t
            status = body.get("status")
            summary = {
                "i": i,
                "question": q,
                "expected": expected,
                "status": status,
                "match": status == expected,
                "latency": round(dt, 1),
            }
            if status == "ok":
                summary["viz"] = body["visualization"]["type"]
                summary["matched"] = body["meta"]["total_trials_matched"]
            elif status == "refused":
                summary["reason"] = body.get("reason")
            elif status == "needs_clarification":
                summary["question_back"] = body.get("question", "")[:80]
            results.append(summary)
            flag = "OK " if summary["match"] else "XX "
            extra = summary.get("viz") or summary.get("reason") or summary.get("status")
            print(f"  {flag}[{dt:4.1f}s] {status:20s} {extra!s:16s} | {q[:52]}")

    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    ok = sum(r["match"] for r in results)
    print(f"\nexpected-status match: {ok}/{len(results)}")
    lats = sorted(r["latency"] for r in results)
    print(f"latency p50={lats[len(lats) // 2]}s  max={lats[-1]}s")


if __name__ == "__main__":
    main()
