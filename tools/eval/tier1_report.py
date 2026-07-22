"""Score the Tier 1 planner-audit results, class-aware, and print a findings report."""

import collections
import json
import sys

rows = [json.loads(l) for l in open(sys.argv[1])]


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


def group(prefix: str) -> list[dict]:
    return [r for r in rows if r["klass"].startswith(prefix)]


# ---------- overall ----------
outcomes = collections.Counter(r["result"]["outcome"] for r in rows)
lats = sorted(r["result"]["latency"] for r in rows)
print(f"=== TIER 1: LLM PLANNER AUDIT (n={len(rows)}) ===")
print(f"outcomes: {dict(outcomes)}")
if lats:
    print(
        f"latency: p50={lats[len(lats) // 2]}s  p95={lats[int(len(lats) * 0.95)]}s  max={lats[-1]}s"
    )
print()

# ---------- supported ----------
sup = group("supported")
by_intent = collections.defaultdict(
    lambda: {
        "n": 0,
        "intent_ok": 0,
        "struct_ok": 0,
        "struct_n": 0,
        "refused": 0,
        "cond_n": 0,
        "cond_ok": 0,
        "intr_n": 0,
        "intr_ok": 0,
    }
)
misplans = []
for r in sup:
    exp_intent = r["expected_intent"]
    ef = r["expected_filters"]
    res = r["result"]
    b = by_intent[exp_intent]
    b["n"] += 1
    if res["outcome"] != "plan":
        b["refused"] += 1
        misplans.append((r["question"], exp_intent, res.get("outcome"), res.get("reason", "")))
        continue
    intent_ok = res.get("intent") == exp_intent
    b["intent_ok"] += intent_ok
    if not intent_ok:
        misplans.append((r["question"], exp_intent, "plan", f"got {res.get('intent')}"))
    # structural checks
    if exp_intent == "distribution":
        b["struct_n"] += 1
        b["struct_ok"] += res.get("dimension") == ef.get("dimension")
    elif exp_intent == "comparison":
        b["struct_n"] += 1
        b["struct_ok"] += (res.get("dimension") == ef.get("dimension")) and len(
            res.get("series", [])
        ) >= 2
    elif exp_intent == "network":
        b["struct_n"] += 1
        b["struct_ok"] += set(res.get("endpoints", [])) == set(ef.get("endpoints", []))
    # entity capture
    if ef.get("condition"):
        b["cond_n"] += 1
        b["cond_ok"] += res.get("condition") is not None
    if ef.get("intervention"):
        b["intr_n"] += 1
        b["intr_ok"] += res.get("intervention") is not None

print(f"SUPPORTED (n={len(sup)}) — correct = right intent (+ structure)")
tot_intent_ok = sum(b["intent_ok"] for b in by_intent.values())
print(f"  overall intent accuracy: {pct(tot_intent_ok, len(sup))}")
print(
    f"  {'intent':14s}{'n':>4}  {'intent✓':>8}  {'struct✓':>8}  {'cond✓':>7}  {'intr✓':>7}  {'refused':>7}"
)
for intent, b in sorted(by_intent.items()):
    print(
        f"  {intent:14s}{b['n']:>4}  {pct(b['intent_ok'], b['n']):>8}  "
        f"{pct(b['struct_ok'], b['struct_n']):>8}  {pct(b['cond_ok'], b['cond_n']):>7}  "
        f"{pct(b['intr_ok'], b['intr_n']):>7}  {pct(b['refused'], b['n']):>7}"
    )
print()

# ---------- unsupported (the acid test) ----------
uns = group("unsupported")
print(f"UNSUPPORTED (n={len(uns)}) — CORRECT = refuse; a plan = force-fit (confident wrong answer)")
refused = [r for r in uns if r["result"]["outcome"] == "refuse"]
forced = [r for r in uns if r["result"]["outcome"] == "plan"]
errored = [r for r in uns if r["result"]["outcome"] == "error"]
print(f"  refused (GOOD):    {len(refused):>4}  ({pct(len(refused), len(uns))})")
print(f"  force-fit (BAD):   {len(forced):>4}  ({pct(len(forced), len(uns))})")
print(f"  errored:           {len(errored):>4}")
if forced:
    landed = collections.Counter(r["result"]["intent"] for r in forced)
    print(f"  force-fit landed as: {dict(landed)}")
print(f"  {'capability':28s}{'n':>4}  {'refuse✓':>8}  {'force-fit':>10}")
by_cap = collections.defaultdict(lambda: [0, 0])
for r in uns:
    cap = r["klass"].split(":", 1)[1]
    by_cap[cap][0] += 1
    by_cap[cap][1] += r["result"]["outcome"] == "refuse"
for cap, (n, ok) in sorted(by_cap.items()):
    print(f"  {cap:28s}{n:>4}  {pct(ok, n):>8}  {pct(n - ok, n):>10}")
print()

# ---------- adversarial ----------
adv = group("adversarial")
print(f"ADVERSARIAL (n={len(adv)})")
for kind in ["out_of_domain", "ambiguous", "too_broad"]:
    g = [r for r in adv if r["klass"].endswith(kind)]
    if not g:
        continue
    if kind == "too_broad":
        ok = sum(r["result"]["outcome"] == "plan" for r in g)  # plan is correct; refused downstream
        print(f"  too_broad      n={len(g):>3}  produced-plan (correct): {pct(ok, len(g))}")
    else:
        ok = sum(r["result"]["outcome"] == "refuse" for r in g)
        print(f"  {kind:14s} n={len(g):>3}  refused (correct): {pct(ok, len(g))}")
print()

# ---------- concrete examples ----------
print("SAMPLE FORCE-FITS (unsupported question -> confident plan):")
for r in forced[:8]:
    print(
        f"  [{r['klass'].split(':')[1]:12s}] -> {r['result']['intent']:12s} | {r['question'][:60]}"
    )
print()
print("SAMPLE SUPPORTED MIS-PLANS / REFUSALS:")
for q, exp, got, detail in misplans[:8]:
    print(f"  expected {exp:12s} got {got:6s} {detail:16s} | {q[:52]}")
