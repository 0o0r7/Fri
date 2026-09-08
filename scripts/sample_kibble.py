"""Sample kibble frames from live technocore.chat to confirm the format.

Run: python scripts/sample_kibble.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter

sys.path.insert(0, ".")

from collector.fetch import fetch_room_messages  # noqa: E402

KIBBLE_RE = re.compile(r"^(JOB|CLAIM|RESULT|DELIVER|ATTEST|ACCEPT)\s+v1\s*\|")

print("=== Sampling 200 messages from /r/kibble ===")
msgs = fetch_room_messages("kibble", limit=200)
print(f"got {len(msgs)} messages\n")

# Categorize
by_type: Counter[str] = Counter()
samples_by_type: dict[str, list[dict]] = {}
for m in msgs:
    text = (m.get("text") or "").strip()
    match = KIBBLE_RE.match(text)
    if match:
        kind = match.group(1)
        by_type[kind] += 1
        if kind not in samples_by_type:
            samples_by_type[kind] = []
        if len(samples_by_type[kind]) < 5:
            samples_by_type[kind].append({
                "seq": m.get("seq"),
                "from": (m.get("from") or "")[:24],
                "ts": m.get("ts"),
                "text": text,
            })

print("=== Frame type counts (200 msg sample) ===")
for kind, count in sorted(by_type.items()):
    print(f"  {kind:8s} {count:>4}")
non_kibble = sum(1 for m in msgs if not KIBBLE_RE.match((m.get("text") or "").strip()))
print(f"  {'(other)':8s} {non_kibble:>4}")

print("\n=== 5 samples per type ===")
for kind in sorted(samples_by_type.keys()):
    print(f"\n--- {kind} ---")
    for s in samples_by_type[kind]:
        print(f"  [#{s['seq']}] {s['from']}: {s['text'][:200]}")

# Now try to parse each type with a regex to see the field structure
print("\n=== Field structure analysis ===")
# JOB v1 | <id> | <category> | <prompt>
# CLAIM v1 | <id> | worker
# RESULT v1 | <id> | <text>
# DELIVER v1 | <id> | <text>
# ATTEST v1 | <id> | <rating> | <ref> | <text>
# ACCEPT v1 | <id> | <text>

job_re = re.compile(r"^JOB v1 \| (k[0-9a-f]+) \| (\w+) \| (.+)$")
claim_re = re.compile(r"^CLAIM v1 \| (k[0-9a-f]+) \| (\w+)$")
result_re = re.compile(r"^RESULT v1 \| (k[0-9a-f]+) \| (.+)$")
deliver_re = re.compile(r"^DELIVER v1 \| (k[0-9a-f]+) \| (.+)$")
attest_re = re.compile(r"^ATTEST v1 \| (k[0-9a-f]+) \| (\w+) \| (\S+) \| (.+)$")
accept_re = re.compile(r"^ACCEPT v1 \| (k[0-9a-f]+) \| (.+)$")

parsers = [
    ("JOB", job_re),
    ("CLAIM", claim_re),
    ("RESULT", result_re),
    ("DELIVER", deliver_re),
    ("ATTEST", attest_re),
    ("ACCEPT", accept_re),
]

for kind, pattern in parsers:
    matches = [m for m in msgs if pattern.match((m.get("text") or "").strip())]
    print(f"  {kind:8s} {len(matches):>4} matched the proposed parser")

# Also check job categories
print("\n=== JOB categories observed ===")
categories: Counter[str] = Counter()
for m in msgs:
    text = (m.get("text") or "").strip()
    match = job_re.match(text)
    if match:
        categories[match.group(2)] += 1
for cat, count in sorted(categories.items()):
    print(f"  {cat:15s} {count:>4}")

# And attest ratings
print("\n=== ATTEST ratings observed ===")
ratings: Counter[str] = Counter()
for m in msgs:
    text = (m.get("text") or "").strip()
    match = attest_re.match(text)
    if match:
        ratings[match.group(2)] += 1
for rating, count in sorted(ratings.items()):
    print(f"  {rating:15s} {count:>4}")

# Check job IDs - how many unique jobs in this sample?
print("\n=== Unique kibble job IDs in sample ===")
job_ids = set()
for m in msgs:
    text = (m.get("text") or "").strip()
    match = KIBBLE_RE.match(text)
    if match:
        # Extract job id (second | separated field)
        parts = text.split("|", 2)
        if len(parts) >= 2:
            job_ids.add(parts[1].strip())
print(f"  {len(job_ids)} unique job IDs")
