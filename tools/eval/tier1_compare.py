"""Compare two Tier 1 audit runs (before/after prompt fix). Same seed => same 500 questions."""

import collections
import json
import sys

before = {r["id"]: r for r in (json.loads(l) for l in open(sys.argv[1]))}
after = {r["id"]: r for r in (json.loads(l) for l in open(sys.argv[2]))}
ids = sorted(set(before) & set(after))


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def outcome(r):
    return r["result"]["outcome"]


sup = [i for i in ids if before[i]["klass"].startswith("supported")]
uns = [i for i in ids if before[i]["klass"].startswith("unsupported")]
adv = [i for i in ids if before[i]["klass"].startswith("adversarial")]

print(f"=== BEFORE vs AFTER prompt hardening (n={len(ids)} identical questions) ===\n")


# ---- supported: guard against over-refusal regression ----
def sup_intent_ok(store):
    return sum(
        outcome(store[i]) == "plan"
        and store[i]["result"].get("intent") == store[i]["expected_intent"]
        for i in sup
    )


b_ok, a_ok = sup_intent_ok(before), sup_intent_ok(after)
over_refused = [i for i in sup if outcome(before[i]) == "plan" and outcome(after[i]) != "plan"]
print(f"SUPPORTED (n={len(sup)})  [regression watch]")
print(f"  intent accuracy:      {pct(b_ok, len(sup))} -> {pct(a_ok, len(sup))}")
print(f"  newly over-refused:   {len(over_refused)}")
for i in over_refused[:6]:
    print(
        f"     ! {before[i]['expected_intent']:12s} now {outcome(after[i])} | {before[i]['question'][:56]}"
    )
print()


# ---- unsupported: the fix target ----
def ff(store, subset):
    return [i for i in subset if outcome(store[i]) == "plan"]


b_ff, a_ff = ff(before, uns), ff(after, uns)
print(f"UNSUPPORTED (n={len(uns)})  [fix target: force-fit = BAD]")
print(
    f"  force-fit rate:       {pct(len(b_ff), len(uns))} ({len(b_ff)}) -> {pct(len(a_ff), len(uns))} ({len(a_ff)})"
)
print(
    f"  refusal rate:         {pct(len(uns) - len(b_ff), len(uns))} -> {pct(len(uns) - len(a_ff), len(uns))}"
)
print(f"  {'capability':16s}{'before':>10}{'after':>10}")
caps = collections.defaultdict(lambda: [0, 0, 0])  # n, ff_before, ff_after
for i in uns:
    cap = before[i]["klass"].split(":")[1]
    caps[cap][0] += 1
    caps[cap][1] += outcome(before[i]) == "plan"
    caps[cap][2] += outcome(after[i]) == "plan"
for cap, (n, fb, fa) in sorted(caps.items()):
    print(f"  {cap:16s}{pct(fb, n):>10}{pct(fa, n):>10}")
fixed = [i for i in b_ff if outcome(after[i]) != "plan"]
new_ff = [i for i in a_ff if outcome(before[i]) != "plan"]
print(f"  fixed (was force-fit, now refuses): {len(fixed)}")
print(f"  NEW force-fits (regressions):       {len(new_ff)}")
for i in new_ff[:6]:
    print(f"     ! now {after[i]['result'].get('intent')} | {before[i]['question'][:56]}")
print()

# ---- adversarial: too_broad must still plan; ood/ambiguous must still refuse ----
print(f"ADVERSARIAL (n={len(adv)})")
tb = [i for i in adv if before[i]["klass"].endswith("too_broad")]
oa = [i for i in adv if not before[i]["klass"].endswith("too_broad")]
tb_b = sum(outcome(before[i]) == "plan" for i in tb)
tb_a = sum(outcome(after[i]) == "plan" for i in tb)
oa_b = sum(outcome(before[i]) == "refuse" for i in oa)
oa_a = sum(outcome(after[i]) == "refuse" for i in oa)
print(f"  too_broad produced-plan (correct): {pct(tb_b, len(tb))} -> {pct(tb_a, len(tb))}")
print(f"  ood/ambiguous refused (correct):   {pct(oa_b, len(oa))} -> {pct(oa_a, len(oa))}")
print()

print("SAMPLE FIXES (force-fit -> refuse):")
for i in fixed[:8]:
    print(
        f"  [{before[i]['klass'].split(':')[1]:12s}] was {before[i]['result'].get('intent'):12s} | {before[i]['question'][:52]}"
    )
