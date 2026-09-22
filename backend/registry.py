"""DID-note registry — the network's durable identity ledger.

Room rings forget (~10 MiB churn — hours under flood traffic), but the
/kv/did-* note namespace is PERSISTENT: a DID profile published there
stays readable no matter what happens to the messages. This module walks
all 256 note shards (did-00 .. did-ff), parses every self-published DID
note ("<did:key:...> <bio>") and registers the identity in the DID index
— zero-activity entries carrying the bio, upgraded in place the moment
any signed message is observed.

For identities whose messages churned out of every ring before FRI ever
sampled them (the exact failure that made the FRI author's own DID
invisible), the registry is the difference between existing and not
existing in the oracle.

Known-note tracking lives in the store as a fingerprint set
(REGISTRY_KNOWN_KEY), so repeated sweeps only fetch NEW notes: one list
request per shard (256) + one note read per new fingerprint. Sweeps run
at boot and every REGISTRY_INTERVAL_S, politely (REGISTRY_DELAY_S between
requests), and abort cleanly on rate limits — the next sweep resumes.

Self-healing reconciliation (2026-09-15): a fingerprint whose durable
entry went missing (store eviction, flush, boot data loss) is re-fetched
and re-registered on every sweep until it persists again — the note
namespace is the source of truth, so the index always converges back to
the full ledger. Junk notes (non-DID bodies) are parked separately
(REGISTRY_JUNK_KEY) so they are read exactly once, never re-fetched.

Priority reconciliation (2026-09-16): the registry turned out to hold
~1.4M notes (256 listing shards, ~5.5k keys each) and — critically — the
SOURCE's listing shards are a client-side convention, not enforced by
the server: third-party writers (flopkit, bots) pick their own shard, so
a note listed under did-00 can carry a DID whose true fingerprint
(sha256(did)[:16]) starts with any hex pair. A sequential pass therefore
takes days and cannot be prioritized. To keep operator-pinned identities
alive anyway, a small persistent priority set (REGISTRY_PRIORITY_KEY,
bootstrapped from the FRI_PRIORITY_DIDS env) is reconciled FIRST on
every sweep — before the shard walk — so pinned DIDs survive eviction
within minutes of any restart, not days.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from collector.config import (
    PRIORITY_DIDS,
    REGISTRY_DELAY_S,
    REGISTRY_HEAL_BUDGET,
    REGISTRY_INTERVAL_S,
    REGISTRY_TIMEOUT_S,
)

try:
    from collector.did_index import did_note_fingerprint
except ImportError:  # pragma: no cover — backend always has collector/
    import hashlib

    def did_note_fingerprint(did: str) -> str:
        return hashlib.sha256(did.encode()).hexdigest()[:16]

log = logging.getLogger("fri.registry")


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

REGISTRY_KNOWN_KEY = "fri:reg:known"
REGISTRY_JUNK_KEY = "fri:reg:junk"
REGISTRY_PRIORITY_KEY = "fri:reg:priority"
SHARD_COUNT = 256  # did-00 .. did-ff — fingerprint hex prefixes

# Observability for /api/debug/sweep: the registry loop records the last
# completed pass here (totals + timing). Pure counters — no DIDs, no bios.
LAST_SWEEP: dict = {"started_at": None, "finished_at": None, "totals": {}}


def parse_note_value(raw: str) -> tuple[str, str] | None:
    """Parse a did-note body into (did, bio).

    The raw GET body may carry an "!! UNTRUSTED CONTENT" banner and blank
    lines before the value; the value itself is "<did> <free text>". A
    body whose first content line does not start with did:key: is junk
    written into the namespace by a third party — skipped, never guessed.
    """
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("!!"):
            continue
        if not line.startswith("did:key:"):
            return None
        parts = line.split(None, 1)
        did = parts[0]
        bio = parts[1].strip() if len(parts) > 1 else ""
        return did, bio
    return None


async def _get(collector, path: str) -> httpx.Response | None:
    """GET with a single 429 retry; None only on real network/5xx failure.

    404 is a VALID answer here (an empty shard / absent note) and is
    returned as a response for the caller to interpret.
    """
    for attempt in range(2):
        try:
            resp = await collector.client.get(
                path,
                timeout=httpx.Timeout(REGISTRY_TIMEOUT_S, connect=10.0),
            )
            if resp.status_code == 429:
                await asyncio.sleep(5.0 * (attempt + 1))
                continue
            return resp
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
    return None


async def _flush_progress(collector, new_fps: list[str], new_junk: list[str]) -> None:
    """Persist swept fingerprints incrementally; clears the batches on success.

    Free-tier spin-downs can kill the sweep mid-flight, and re-fetching
    every note from scratch on every boot would make the first full pass
    never finish. Failures are logged and swallowed — the next flush
    retries with a superset.
    """
    if not new_fps and not new_junk:
        return
    try:
        if new_fps:
            await collector.store.sadd(REGISTRY_KNOWN_KEY, new_fps)
            new_fps.clear()
        if new_junk:
            await collector.store.sadd(REGISTRY_JUNK_KEY, new_junk)
            new_junk.clear()
    except Exception as e:
        log.warning("registry known-set flush failed: %s", e)


async def _reconcile_priority(
    collector,
    totals: dict[str, int],
    known: set[str],
    junk: set[str],
    index_fps: set[str],
    missing: set[str],
    new_fps: list[str],
    new_junk: list[str],
) -> None:
    """Reconcile the operator's pinned fingerprints before the shard walk.

    The persistent fri:reg:priority set is merged with the FRI_PRIORITY_DIDS
    env bootstrap (so the env can add pins without touching the store, and
    the store keeps pins across deploys that drop the env). Each pinned
    fingerprint absent from the live index — and not parked junk — is
    re-fetched and re-registered immediately.
    """
    priority: set[str] = set()
    try:
        priority = await collector.store.smembers(REGISTRY_PRIORITY_KEY)
    except Exception:
        priority = set()
    env_fps = {did_note_fingerprint(d) for d in PRIORITY_DIDS}
    if env_fps - priority:
        priority |= env_fps
        try:
            await collector.store.sadd(REGISTRY_PRIORITY_KEY, sorted(env_fps))
        except Exception as e:
            log.warning("priority bootstrap flush failed: %s", e)
    if not priority:
        return
    for fp in sorted(priority):
        if fp in junk or fp in index_fps:
            continue  # parked junk / alive in the index — nothing to heal
        note = await _get(collector, f"/kv/did-{fp[:2]}/{fp[2:]}")
        await asyncio.sleep(REGISTRY_DELAY_S)
        if note is None or note.status_code != 200:
            continue
        parsed = parse_note_value(note.text)
        if parsed is None:
            new_junk.append(fp)
            continue
        did, bio = parsed
        existed = collector.did_index.get(did) is not None
        collector.did_index.register_identity(did, bio or None)
        totals["notes"] += 1
        if not existed:
            totals["registered"] += 1
        totals["priority_healed"] += 1
        if fp in known:
            totals["healed"] += 1
        new_fps.append(fp)
        known.add(fp)  # the shard walk below must not re-fetch it
        missing.discard(fp)
    log.info(
        "registry priority pass: %d pinned fps, %d healed",
        len(priority),
        totals["priority_healed"],
    )


async def sweep_once(collector) -> dict[str, int]:
    """Walk every shard, register unseen did-notes. Never raises.

    Reconciliation: a fingerprint already in the known set is skipped
    only when its entry still exists in the live index. Known-but-missing
    fingerprints (durable-store eviction, flush, boot data loss) are
    re-fetched and re-registered — the note namespace is persistent, so
    the index converges back to the full ledger within one sweep.
    """
    totals = {
        "shards": 0,
        "notes": 0,
        "registered": 0,
        "failed_shards": 0,
        "healed": 0,
        "priority_healed": 0,
    }
    known: set[str] = set()
    junk: set[str] = set()
    try:
        known = await collector.store.smembers(REGISTRY_KNOWN_KEY)
    except Exception:
        known = set()
    try:
        junk = await collector.store.smembers(REGISTRY_JUNK_KEY)
    except Exception:
        junk = set()

    # Fingerprints currently tracked by the live index. A known fingerprint
    # absent from here is a lost entry — it must be re-fetched, not skipped.
    index_fps: set[str] = set()
    try:
        index_fps = {
            did_note_fingerprint(d) for d in collector.did_index.dids()
        }
    except Exception:
        index_fps = set()  # worst case: re-fetch everything known, politely
    missing_all = known - index_fps - junk
    # Heal budget (2026-09-22 free-tier hardening): bound the re-fetch work
    # per sweep. Without it, a pruned durable store turns every sweep into
    # a 200k+ note re-fetch treadmill — the polite-flood CPU burn that
    # helped wedge F1. Priority-pinned DIDs heal unconditionally above;
    # the rest converge back gradually, REGISTRY_HEAL_BUDGET per sweep.
    missing = set(sorted(missing_all)[:REGISTRY_HEAL_BUDGET])
    if len(missing_all) > len(missing):
        log.info(
            "registry heal budget: %d known-but-missing fps, healing %d this "
            "sweep (budget %d)",
            len(missing_all),
            len(missing),
            REGISTRY_HEAL_BUDGET,
        )
    new_fps: list[str] = []
    new_junk: list[str] = []

    # Pinned identities first — see _reconcile_priority. Runs before the
    # shard walk so a pin lost to eviction heals within seconds of the
    # sweep starting, not days later when the walk reaches its shard.
    await _reconcile_priority(
        collector, totals, known, junk, index_fps, missing, new_fps, new_junk
    )
    await _flush_progress(collector, new_fps, new_junk)

    for shard_idx in range(SHARD_COUNT):
        shard = f"did-{shard_idx:02x}"
        resp = await _get(collector, f"/kv/{shard}")
        if resp is None or resp.status_code >= 500:
            # Network/5xx failure — count and move on; the next sweep
            # re-checks this shard.
            totals["failed_shards"] += 1
            await asyncio.sleep(REGISTRY_DELAY_S)
            continue
        totals["shards"] += 1
        if resp.status_code == 404:
            # Empty shard — a valid, if boring, answer.
            await asyncio.sleep(REGISTRY_DELAY_S)
            continue
        for line in resp.text.splitlines():
            key = line.strip().split("/")[-1]
            if not key:
                continue
            fp = f"{shard[4:]}{key}"  # shard suffix + key = full fingerprint
            if fp in junk:
                continue  # parked junk — read exactly once, ever
            if fp in known and fp not in missing:
                continue
            note = await _get(collector, f"/kv/{shard}/{key}")
            await asyncio.sleep(REGISTRY_DELAY_S)
            if note is None or note.status_code != 200:
                continue
            parsed = parse_note_value(note.text)
            if parsed is None:
                # Junk in the namespace — park it forever so we never
                # re-read it, but register nothing.
                new_junk.append(fp)
                if len(new_fps) >= 200 or len(new_junk) >= 200:
                    await _flush_progress(collector, new_fps, new_junk)
                continue
            did, bio = parsed
            existed = collector.did_index.get(did) is not None
            collector.did_index.register_identity(did, bio or None)
            totals["notes"] += 1
            if not existed:
                totals["registered"] += 1
            if fp in known:
                totals["healed"] += 1
            new_fps.append(fp)
            # Flush progress incrementally, MID-SHARD: a big listing shard
            # takes ~40 min at the polite cadence, and a restart before the
            # shard boundary used to lose the whole batch (the known-set
            # stayed empty for hours on a fresh store). Flush every 200.
            if len(new_fps) >= 200 or len(new_junk) >= 200:
                await _flush_progress(collector, new_fps, new_junk)
        await asyncio.sleep(REGISTRY_DELAY_S)
        if shard_idx % 32 == 31:
            log.info(
                "registry sweep %d/256 shards: %d notes (%d new, %d healed)",
                shard_idx + 1,
                totals["notes"],
                totals["registered"],
                totals["healed"],
            )

    await _flush_progress(collector, new_fps, new_junk)
    return totals


async def registry_loop(collector) -> None:
    """Boot sweep + periodic re-sweep for newly published notes."""
    first = True
    while True:
        if not first:
            await asyncio.sleep(REGISTRY_INTERVAL_S)
        first = False
        started = time.time()
        LAST_SWEEP["started_at"] = _utcnow()
        log.info("DID-note registry sweep starting (256 shards)")
        try:
            totals = await sweep_once(collector)
            LAST_SWEEP["finished_at"] = _utcnow()
            LAST_SWEEP["totals"] = dict(totals)
            log.info(
                "Registry sweep done in %.0fs: %d shards read (%d failed), "
                "%d notes parsed, %d identities registered",
                time.time() - started,
                totals["shards"],
                totals["failed_shards"],
                totals["notes"],
                totals["registered"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LAST_SWEEP["finished_at"] = _utcnow()
            LAST_SWEEP["error"] = str(e)[:200]
            log.warning("registry sweep crashed (retries next cycle): %s", e)
