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
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from collector.config import (
    REGISTRY_DELAY_S,
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

REGISTRY_KNOWN_KEY = "fri:reg:known"
SHARD_COUNT = 256  # did-00 .. did-ff — fingerprint hex prefixes


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


async def sweep_once(collector) -> dict[str, int]:
    """Walk every shard, register unseen did-notes. Never raises."""
    totals = {"shards": 0, "notes": 0, "registered": 0, "failed_shards": 0}
    known: set[str] = set()
    try:
        known = await collector.store.smembers(REGISTRY_KNOWN_KEY)
    except Exception:
        known = set()
    new_fps: list[str] = []

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
            if fp in known:
                continue
            note = await _get(collector, f"/kv/{shard}/{key}")
            await asyncio.sleep(REGISTRY_DELAY_S)
            if note is None or note.status_code != 200:
                continue
            parsed = parse_note_value(note.text)
            if parsed is None:
                # Junk in the namespace — remember the fingerprint so we
                # never re-read it, but register nothing.
                new_fps.append(fp)
                continue
            did, bio = parsed
            created = collector.did_index.register_identity(did, bio or None)
            totals["notes"] += 1
            if created:
                totals["registered"] += 1
            new_fps.append(fp)
        # Flush progress incrementally: free-tier spin-downs can kill the
        # sweep mid-flight, and re-fetching every note from scratch on
        # every boot would make the first full pass never finish.
        if len(new_fps) >= 200:
            try:
                await collector.store.sadd(REGISTRY_KNOWN_KEY, new_fps)
                new_fps = []
            except Exception as e:
                log.warning("registry known-set flush failed: %s", e)
        await asyncio.sleep(REGISTRY_DELAY_S)
        if shard_idx % 32 == 31:
            log.info(
                "registry sweep %d/256 shards: %d notes (%d new)",
                shard_idx + 1,
                totals["notes"],
                totals["registered"],
            )

    if new_fps:
        try:
            await collector.store.sadd(REGISTRY_KNOWN_KEY, new_fps)
        except Exception as e:
            log.warning("registry known-set persist failed: %s", e)
    return totals


async def registry_loop(collector) -> None:
    """Boot sweep + periodic re-sweep for newly published notes."""
    first = True
    while True:
        if not first:
            await asyncio.sleep(REGISTRY_INTERVAL_S)
        first = False
        started = time.time()
        log.info("DID-note registry sweep starting (256 shards)")
        try:
            totals = await sweep_once(collector)
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
            log.warning("registry sweep crashed (retries next cycle): %s", e)
