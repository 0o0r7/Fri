"""Sample tclk1 frames from live technocore.chat to confirm format and coverage.

Run: python scripts/sample_tclk.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.path.insert(0, ".")

from collector.fetch import fetch_room_messages  # noqa: E402

TCLK_RE = re.compile(r"^tclk1\s+(\{.*\})\s*$")


def try_parse(text: str) -> dict | None:
    m = TCLK_RE.match((text or "").strip())
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


print("=== Sampling 200 messages from /r/tclk-offers ===")
msgs = fetch_room_messages("tclk-offers", limit=200)
print(f"got {len(msgs)} messages\n")

# Categorize
by_type: Counter[str] = Counter()
samples_by_type: dict[str, list[dict]] = {}
parse_failures = 0
for m in msgs:
    text = (m.get("text") or "").strip()
    parsed = try_parse(text)
    if parsed is None:
        if text.startswith("tclk1 "):
            parse_failures += 1
        continue
    kind = parsed.get("type", "?")
    by_type[kind] += 1
    if kind not in samples_by_type:
        samples_by_type[kind] = []
    if len(samples_by_type[kind]) < 3:
        samples_by_type[kind].append({
            "seq": m.get("seq"),
            "from": (m.get("from") or "")[:24],
            "ts": m.get("ts"),
            "parsed": parsed,
        })

print("=== Frame type counts (200 msg sample) ===")
for kind, count in sorted(by_type.items()):
    print(f"  {kind:12s} {count:>4}")
non_tclk = sum(1 for m in msgs if not (m.get("text") or "").strip().startswith("tclk1 "))
print(f"  {'(non-tclk)':12s} {non_tclk:>4}")
print(f"  {'(parse fail)':12s} {parse_failures:>4}")

print("\n=== 3 samples per type ===")
for kind in sorted(samples_by_type.keys()):
    print(f"\n--- {kind} ---")
    for s in samples_by_type[kind]:
        print(f"  [#{s['seq']}] from {s['from']}")
        print(f"  parsed: {json.dumps(s['parsed'], sort_keys=True)}")

# Field analysis per type
print("\n=== Field analysis ===")
fields_by_type: dict[str, set[str]] = {}
for kind_samples in samples_by_type.values():
    for s in kind_samples:
        kind = s["parsed"].get("type", "?")
        if kind not in fields_by_type:
            fields_by_type[kind] = set()
        fields_by_type[kind].update(s["parsed"].keys())

for kind, fields in sorted(fields_by_type.items()):
    print(f"  {kind:12s} fields: {sorted(fields)}")

# Rails observed
print("\n=== Rails observed ===")
rails: Counter[str] = Counter()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if "rails" in parsed and isinstance(parsed["rails"], list):
            for r in parsed["rails"]:
                rails[r] += 1
        if "rail" in parsed:
            rails[parsed["rail"]] += 1
for r, count in sorted(rails.items()):
    print(f"  {r:20s} {count:>4}")

# Assets observed
print("\n=== Assets observed ===")
assets: Counter[str] = Counter()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if "asset" in parsed:
            assets[parsed["asset"]] += 1
for a, count in sorted(assets.items()):
    print(f"  {a:20s} {count:>4}")

# Roles observed (offer only)
print("\n=== Roles observed (offer) ===")
roles: Counter[str] = Counter()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if parsed.get("type") == "offer" and "role" in parsed:
            roles[parsed["role"]] += 1
for r, count in sorted(roles.items()):
    print(f"  {r:20s} {count:>4}")

# Job protocols observed
print("\n=== Job protocols observed ===")
protos: Counter[str] = Counter()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if "job" in parsed and isinstance(parsed["job"], dict):
            p = parsed["job"].get("proto", "?")
            protos[p] += 1
for p, count in sorted(protos.items()):
    print(f"  {p:20s} {count:>4}")

# Amount range
print("\n=== Amount range (offer) ===")
amounts = []
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if parsed.get("type") == "offer" and "amount" in parsed:
            try:
                amounts.append(int(parsed["amount"]))
            except (ValueError, TypeError):
                pass
if amounts:
    print(f"  min: {min(amounts)}")
    print(f"  max: {max(amounts)}")
    print(f"  median: {sorted(amounts)[len(amounts) // 2]}")
    print(f"  count: {len(amounts)}")

# Unique contract ids (from non-offer frames)
print("\n=== Unique contract ids ===")
contract_ids = set()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if "contract" in parsed:
            contract_ids.add(parsed["contract"])
        if "id" in parsed and parsed.get("type") == "offer":
            contract_ids.add(parsed["id"])
print(f"  {len(contract_ids)} unique contract/offer ids in sample")

# Outcomes (receipt only)
print("\n=== Receipt outcomes observed ===")
outcomes: Counter[str] = Counter()
for s_list in samples_by_type.values():
    for s in s_list:
        parsed = s["parsed"]
        if parsed.get("type") == "receipt" and "outcome" in parsed:
            outcomes[parsed["outcome"]] += 1
for o, count in sorted(outcomes.items()):
    print(f"  {o:20s} {count:>4}")
