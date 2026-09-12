"""TCLK Module — Phase 3 of FRI.

Detects and parses tclk/1 frames from sampled room messages.

tclk/1 is the Technocore Lock Protocol — Flop Labs's signed HTLC/PTLC
deal-making convention. Two agents that met in a technocore room strike
a deal as signed messages: offer → accept → lock → reveal (or refund) →
receipt. Money lives on a separately-named settlement rail (paper, flop-htlc,
x402, evm-htlc, etc.); the room only coordinates.

Frame format (one line):
    tclk1 {"type":"offer","amount":"1000","asset":"FLOP",...}

The JSON is canonical (sorted keys, compact separators, ASCII-escaped).
We parse it leniently — malformed frames are recorded but don't crash.

Full spec: https://github.com/flop-labs/tclk/blob/main/SPEC.md

This module produces two artifacts:
    - data/tclk.json — per-contract index + aggregate deal-flow stats
    - (Phase 4 will fold per-DID deal stats into the DID reputation score)

Refund rate is the critical reputation signal. A high refund rate means
the worker (payee) is unreliable: they accept deals but don't reveal the
secret before refundAfterMs, so the payer has to refund. A low refund rate
with high receipt count means the worker reliably delivers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Frame detection + parsing
# ---------------------------------------------------------------------------

TCLK_RE = re.compile(r"^tclk1\s+(\{.*\})\s*$")

# The 8 frame types defined in tclk/1 SPEC §3.
KNOWN_FRAME_TYPES = frozenset({
    "offer",
    "accept",
    "lock",
    "reveal",
    "refund",
    "cancel",
    "receipt",
    "heartbeat",
})

# Receipt outcomes (SPEC §3.5)
KNOWN_OUTCOMES = frozenset({"claimed", "refunded", "cancelled"})

# Known settlement rails (SPEC §5)
KNOWN_RAILS = frozenset({
    "paper",
    "memory",
    "flop-htlc",
    "evm-htlc",
    "btc-htlc",
    "near-htlc",
    "x402",
})


def _int(value: Any, default: int = 0) -> int:
    """Lenient int coercion for committed-JSON fields (None/garbage → default)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def parse_frame(text: str) -> Optional[dict]:
    """Try to parse a tclk1 frame from a single message text.

    Returns the parsed JSON dict on success (always includes "type"), or
    None if the text is not a tclk1 frame. Malformed JSON inside a tclk1
    prefix returns None — we don't try to recover broken frames.
    """
    stripped = (text or "").strip()
    m = TCLK_RE.match(stripped)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if "type" not in parsed:
        return None
    return parsed


# ---------------------------------------------------------------------------
# Contract accumulator
# ---------------------------------------------------------------------------


@dataclass
class TclkContract:
    """All frames we've seen for one tclk contract.

    A contract is identified by its `contract` id, which is sha256 of the
    offer+accept binding (SPEC §3.2). For the offer frame itself, the id
    is the offer's `id` field; once accepted, both sides derive the same
    contract id and all subsequent frames reference it.

    We index contracts by both the offer `id` and the `contract` id, so
    a single contract can be looked up either way.
    """

    contract_id: str  # the canonical id (offer.id initially, then contract)
    offer: Optional[dict] = None  # the offer frame
    accept: Optional[dict] = None  # the accept frame (first one wins)
    locks: List[dict] = field(default_factory=list)
    reveals: List[dict] = field(default_factory=list)
    refunds: List[dict] = field(default_factory=list)
    cancels: List[dict] = field(default_factory=list)
    receipts: List[dict] = field(default_factory=list)
    heartbeats: List[dict] = field(default_factory=list)
    first_seen_ts: Optional[str] = None
    last_activity_ts: Optional[str] = None
    # True when this contract's offer has been linked to a contract-id
    # contract (i.e., the offer was accepted). Used by did_stats to avoid
    # double-counting: the deal is counted via the contract-id contract.
    offer_linked_elsewhere: bool = False

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Derived state, in increasing order of completion.

        proposed → accepted → locked → revealed → receipted
        (refund and cancel are terminal, refund wins over reveal if both
        happened — but that's a rail dispute, not something we arbitrate)

        Returns the highest state we have evidence for:
            proposed → accepted → locked → revealed → receipted
            (or "refunded" / "cancelled" if terminal frames exist)
        """
        if self.receipts:
            # Use the receipt outcome as the most authoritative state
            outcome = self.receipts[0].get("outcome")
            if outcome in KNOWN_OUTCOMES:
                return outcome
            return "receipted"
        if self.refunds:
            return "refunded"
        if self.cancels:
            return "cancelled"
        if self.reveals:
            return "revealed"
        if self.locks:
            return "locked"
        if self.accept:
            return "accepted"
        return "proposed"

    @property
    def payer_did(self) -> Optional[str]:
        """The payer (offer maker). For a payer-role offer, that's `offer.from`.
        For a payee-role offer, that's the accepter — but we don't see those
        in our sample, so we handle the simple case."""
        if not self.offer:
            return None
        if self.offer.get("role") == "payer":
            return self.offer.get("from")
        # payee-role offer: payer is whoever accepts. Rare; we don't see it.
        if self.accept:
            return self.accept.get("from")
        return None

    @property
    def payee_did(self) -> Optional[str]:
        """The payee (the one who mints the secret and reveals it)."""
        if not self.offer:
            return None
        if self.offer.get("role") == "payer":
            # payee is whoever accepts
            return self.accept.get("from") if self.accept else None
        # payee-role offer: payee is the offer maker
        return self.offer.get("from")

    @property
    def amount(self) -> Optional[str]:
        if self.offer:
            return self.offer.get("amount")
        return None

    @property
    def asset(self) -> Optional[str]:
        if self.offer:
            return self.offer.get("asset")
        return None

    @property
    def rails(self) -> List[str]:
        if self.offer and isinstance(self.offer.get("rails"), list):
            return self.offer["rails"]
        return []

    @property
    def lock_kind(self) -> Optional[str]:
        if self.offer:
            return self.offer.get("lock")
        return None

    @property
    def job(self) -> Optional[dict]:
        if self.offer and isinstance(self.offer.get("job"), dict):
            return self.offer["job"]
        return None

    @property
    def receipt_outcome(self) -> Optional[str]:
        if self.receipts:
            return self.receipts[0].get("outcome")
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "state": self.state,
            "payer_did": self.payer_did,
            "payee_did": self.payee_did,
            "amount": self.amount,
            "asset": self.asset,
            "rails": self.rails,
            "lock_kind": self.lock_kind,
            "job": self.job,
            "offer_ts": self.offer.get("_ts") if self.offer else None,
            "accept_ts": self.accept.get("_ts") if self.accept else None,
            "lock_count": len(self.locks),
            "reveal_count": len(self.reveals),
            "refund_count": len(self.refunds),
            "cancel_count": len(self.cancels),
            "receipt_count": len(self.receipts),
            "receipt_outcome": self.receipt_outcome,
            "heartbeat_count": len(self.heartbeats),
            "first_seen": self.first_seen_ts,
            "last_activity": self.last_activity_ts,
            "offer_frame": self.offer,  # full frame for inspection
        }


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class TclkIndex:
    """In-memory index of every tclk/1 contract we've seen.

    Call `ingest_message` for every message in every room we sample, then
    `snapshot()` to get the JSON-serializable payload.
    """

    def __init__(self) -> None:
        # Indexed by contract_id (which is offer.id for proposed contracts,
        # then contract for accepted+ ones). We also keep an alias map from
        # offer.id → contract_id for lookups.
        self._contracts: Dict[str, TclkContract] = {}
        self._offer_id_to_contract: Dict[str, str] = {}
        self._total_frames: int = 0
        self._total_messages_sampled: int = 0
        self._frames_by_type: Dict[str, int] = {t: 0 for t in KNOWN_FRAME_TYPES}
        self._frames_by_type["unknown"] = 0
        self._parse_failures: int = 0

    def ingest_message(self, room: str, message: Dict[str, Any]) -> None:
        self._total_messages_sampled += 1
        text = message.get("text") or ""
        parsed = parse_frame(text)
        if parsed is None:
            if text.strip().startswith("tclk1 "):
                self._parse_failures += 1
            return

        self._total_frames += 1
        ftype = parsed.get("type", "unknown")
        if ftype in self._frames_by_type:
            self._frames_by_type[ftype] += 1
        else:
            self._frames_by_type["unknown"] += 1

        did = parsed.get("from") or ""
        ts = message.get("ts") or ""
        seq = message.get("seq")
        if not isinstance(seq, int):
            seq = None

        # Stash ts/seq on the frame for later use in to_dict
        parsed["_ts"] = ts
        parsed["_seq"] = seq
        parsed["_room"] = room

        # Route to the right contract
        if ftype == "offer":
            contract_id = parsed.get("id") or ""
            if not contract_id:
                return  # malformed offer without id
            contract = self._contracts.get(contract_id)
            if contract is None:
                contract = TclkContract(contract_id=contract_id)
                self._contracts[contract_id] = contract
                self._offer_id_to_contract[contract_id] = contract_id
            # First offer wins; subsequent are replays
            if contract.offer is None:
                contract.offer = parsed
            self._update_ts(contract, ts)
        else:
            # All other frames reference `contract` field
            contract_id = parsed.get("contract") or ""
            if not contract_id:
                return  # malformed frame without contract id
            contract = self._contracts.get(contract_id)
            if contract is None:
                contract = TclkContract(contract_id=contract_id)
                self._contracts[contract_id] = contract

            if ftype == "accept":
                if contract.accept is None:
                    contract.accept = parsed
                    # Link the offer: the accept's `ref` field is the offer id.
                    # Pull the offer frame from the offer-id contract so this
                    # contract has full context for payer/payee/amount/etc.
                    offer_id = parsed.get("ref") or ""
                    if offer_id:
                        offer_contract = self._contracts.get(offer_id)
                        if offer_contract and offer_contract.offer and contract.offer is None:
                            contract.offer = offer_contract.offer
                            # Mark the offer-id contract so did_stats skips it
                            offer_contract.offer_linked_elsewhere = True
                        # Map the offer id to this contract for future lookups
                        self._offer_id_to_contract[offer_id] = contract_id
            elif ftype == "lock":
                contract.locks.append(parsed)
            elif ftype == "reveal":
                contract.reveals.append(parsed)
            elif ftype == "refund":
                contract.refunds.append(parsed)
            elif ftype == "cancel":
                contract.cancels.append(parsed)
            elif ftype == "receipt":
                contract.receipts.append(parsed)
            elif ftype == "heartbeat":
                contract.heartbeats.append(parsed)

            self._update_ts(contract, ts)

    def _update_ts(self, contract: TclkContract, ts: str) -> None:
        if not ts:
            return
        if contract.first_seen_ts is None or ts < contract.first_seen_ts:
            contract.first_seen_ts = ts
        if contract.last_activity_ts is None or ts > contract.last_activity_ts:
            contract.last_activity_ts = ts

    def ingest_messages(self, room: str, messages: List[Dict[str, Any]]) -> None:
        for m in messages:
            self.ingest_message(room, m)

    def get(self, contract_id: str) -> Optional[TclkContract]:
        return self._contracts.get(contract_id)

    def get_by_offer_id(self, offer_id: str) -> Optional[TclkContract]:
        contract_id = self._offer_id_to_contract.get(offer_id)
        if contract_id is None:
            return None
        return self._contracts.get(contract_id)

    # ------------------------------------------------------------------
    # Per-DID deal stats (used by Phase 4 reputation scoring)
    # ------------------------------------------------------------------

    def did_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute per-DID TCLK deal activity.

        For each DID we've seen in any tclk frame, count:
          - offers_made (as payer or payee, depending on role)
          - offers_accepted (as the accepter)
          - locks_posted (as payer, since only payer locks)
          - reveals_posted (as payee, since only payee reveals)
          - refunds_posted (as payer, since only payer refunds)
          - cancels_posted
          - receipts_posted (with outcome breakdown: claimed/refunded/cancelled)
          - deals_completed (receipts with outcome=claimed where this DID is payee)
          - deals_refunded (receipts with outcome=refunded where this DID is payer)
          - refund_rate = deals_refunded / (deals_completed + deals_refunded)

        The refund_rate is the critical reputation signal. A high refund
        rate means the worker (payee) accepts deals but doesn't reveal in
        time — unreliable. A low refund rate means reliable delivery.
        """
        stats: Dict[str, Dict[str, Any]] = {}

        def bump(did: str, key: str, n: int = 1) -> None:
            if not did:
                return
            if did not in stats:
                stats[did] = {
                    "offers_made": 0,
                    "offers_accepted": 0,
                    "locks_posted": 0,
                    "reveals_posted": 0,
                    "refunds_posted": 0,
                    "cancels_posted": 0,
                    "receipts_posted": 0,
                    "receipts_claimed": 0,
                    "receipts_refunded": 0,
                    "receipts_cancelled": 0,
                    # Outcome-as-party (from the contract's perspective)
                    "deals_as_payer": 0,
                    "deals_as_payee": 0,
                    "deals_completed_as_payee": 0,
                    "deals_refunded_as_payer": 0,
                }
            stats[did][key] = stats[did].get(key, 0) + n

        for contract in self._contracts.values():
            # Skip contracts whose offer was linked to a contract-id contract
            # (i.e., the offer was accepted). The deal is counted via the
            # contract-id contract to avoid double-counting.
            if contract.offer_linked_elsewhere:
                continue

            # Skip contracts that never got accepted — those are just unaccepted
            # offers, not deals. We still count the offer itself for the offerer.
            if contract.accept is None:
                if contract.offer:
                    bump(contract.offer.get("from", ""), "offers_made")
                continue

            payer = contract.payer_did
            payee = contract.payee_did

            if contract.offer:
                bump(contract.offer.get("from", ""), "offers_made")
            if contract.accept:
                bump(contract.accept.get("from", ""), "offers_accepted")
            for lock in contract.locks:
                bump(lock.get("from", ""), "locks_posted")
            for reveal in contract.reveals:
                bump(reveal.get("from", ""), "reveals_posted")
            for refund in contract.refunds:
                bump(refund.get("from", ""), "refunds_posted")
            for cancel in contract.cancels:
                bump(cancel.get("from", ""), "cancels_posted")
            for receipt in contract.receipts:
                bump(receipt.get("from", ""), "receipts_posted")
                outcome = receipt.get("outcome")
                if outcome == "claimed":
                    bump(receipt.get("from", ""), "receipts_claimed")
                elif outcome == "refunded":
                    bump(receipt.get("from", ""), "receipts_refunded")
                elif outcome == "cancelled":
                    bump(receipt.get("from", ""), "receipts_cancelled")

            # Contract-level: count payer/payee role participation and outcomes
            if payer:
                bump(payer, "deals_as_payer")
            if payee:
                bump(payee, "deals_as_payee")

            # If there's a receipt, attribute the outcome to the right party
            if contract.receipts:
                outcome = contract.receipt_outcome
                if outcome == "claimed" and payee:
                    # Payee successfully revealed and claimed
                    bump(payee, "deals_completed_as_payee")
                elif outcome == "refunded" and payer:
                    # Payer had to refund — payee failed to deliver
                    bump(payer, "deals_refunded_as_payer")

        # Compute refund_rate per DID (only for DIDs that have been a payer
        # at least once and have at least one refund or completion)
        for did, s in stats.items():
            total = s["deals_completed_as_payee"] + s["deals_refunded_as_payer"]
            # Note: refund_rate from the payee's perspective would be
            # (deals_refunded_on_deals_they_accepted) / (total deals they accepted)
            # but we don't track that cross-cut. The simpler payer-side metric
            # is: of deals where I was payer, how many ended in refund?
            deals_as_payer = s["deals_as_payer"]
            if deals_as_payer > 0:
                s["refund_rate_as_payer"] = round(
                    s["deals_refunded_as_payer"] / deals_as_payer, 3
                )
            else:
                s["refund_rate_as_payer"] = None

        return stats

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, top_limit: int = 500) -> Dict[str, Any]:
        """Return the JSON-serializable payload for data/tclk.json."""
        contracts = list(self._contracts.values())
        # Sort by last_activity descending
        contracts.sort(key=lambda c: c.last_activity_ts or "", reverse=True)
        top = contracts[:top_limit]

        # Aggregate stats
        state_counts: Dict[str, int] = {}
        rail_counts: Dict[str, int] = {}
        asset_counts: Dict[str, int] = {}
        outcome_counts: Dict[str, int] = {}
        for c in self._contracts.values():
            state_counts[c.state] = state_counts.get(c.state, 0) + 1
            for r in c.rails:
                rail_counts[r] = rail_counts.get(r, 0) + 1
            if c.asset:
                asset_counts[c.asset] = asset_counts.get(c.asset, 0) + 1
            if c.receipt_outcome:
                outcome_counts[c.receipt_outcome] = (
                    outcome_counts.get(c.receipt_outcome, 0) + 1
                )

        return {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "https://technocore.chat",
            "protocol_version": "tclk1",
            "spec_url": "https://github.com/flop-labs/tclk/blob/main/SPEC.md",
            "total_contracts": len(self._contracts),
            "total_frames": self._total_frames,
            "total_messages_sampled": self._total_messages_sampled,
            "parse_failures": self._parse_failures,
            "frames_by_type": dict(self._frames_by_type),
            "contracts_by_state": state_counts,
            "contracts_by_rail": rail_counts,
            "contracts_by_asset": asset_counts,
            "receipts_by_outcome": outcome_counts,
            "contracts": [c.to_dict() for c in top],
        }

    # ------------------------------------------------------------------
    # Hydration (boot-time restore from committed batch JSON)
    # ------------------------------------------------------------------

    def hydrate(self, payload: Dict[str, Any]) -> int:
        """Restore index state from a tclk.json-shaped payload (boot-time).

        tclk.json publishes the full offer frame plus per-frame-type counts
        and the payer/payee DIDs, so hydrate() rebuilds each contract with:

          - the real offer frame — payer/payee/amount/asset/rails/lock_kind
            all derive from it and round-trip exactly
          - a synthetic accept frame when the contract progressed past
            "proposed". Its `from` is chosen so the payer_did/payee_did
            properties reproduce the published values for all three offer
            shapes: role="payer" → accepter is the payee; role="payee" or
            role missing → the payer_did property derives the payer from
            the accept frame, so the accepter is the published payer.
          - synthetic lock/reveal/refund/cancel/receipt/heartbeat frames so
            per-type counts and the derived `state` round-trip exactly.
            Lock/refund frames carry the payer, reveal frames the payee —
            the roles did_stats() attributes them to; cancel/receipt
            authors are not published and stay "" (no invented attribution).
            The receipt outcome is restored verbatim.

        Contracts whose offer id is also the id of a *different* (accepted)
        contract are the raw offer-keyed entries that live ingest keeps in
        parallel; they are restored with offer_linked_elsewhere=True so
        did_stats() does not double-count the deal — identical to live
        behavior after an accept links the offer.

        Frame fields not published in the snapshot (seq, raw text, non-offer
        authors) are placeholders; every rebuilt frame is marked
        "_synthetic": True. Entries already present are skipped (idempotent;
        live ingest wins — a replayed offer/accept hits the "first one wins"
        guards in ingest_message). Returns the number of contracts restored.
        """
        self._total_messages_sampled = max(
            self._total_messages_sampled, _int(payload.get("total_messages_sampled"))
        )
        self._total_frames = max(
            self._total_frames, _int(payload.get("total_frames"))
        )
        self._parse_failures = max(
            self._parse_failures, _int(payload.get("parse_failures"))
        )
        for ftype, n in (payload.get("frames_by_type") or {}).items():
            self._frames_by_type[ftype] = max(
                self._frames_by_type.get(ftype, 0), _int(n)
            )

        entries = [e for e in payload.get("contracts", []) if isinstance(e, dict)]

        # Offer ids referenced by a *different* contract id → those offers
        # were accepted (the accepted contract carries a copy of the frame).
        accepted_offer_ids = set()
        for e in entries:
            oid = (e.get("offer_frame") or {}).get("id")
            if oid and oid != e.get("contract_id"):
                accepted_offer_ids.add(oid)

        restored = 0
        for e in entries:
            cid = e.get("contract_id")
            if not cid or cid in self._contracts:
                continue
            offer = e.get("offer_frame")
            if isinstance(offer, dict):
                offer = dict(offer)  # own copy — live ingest mutates frames
                if "_ts" not in offer and e.get("offer_ts"):
                    offer["_ts"] = e.get("offer_ts")
            else:
                offer = None
            contract = TclkContract(
                contract_id=cid,
                offer=offer,
                first_seen_ts=e.get("first_seen"),
                last_activity_ts=e.get("last_activity"),
            )
            state = e.get("state") or "proposed"

            if state != "proposed" and contract.accept is None:
                role = (offer or {}).get("role")
                if role == "payer":
                    accepter = e.get("payee_did")
                else:
                    # payee-role or role-less offers: the accepter IS the payer
                    accepter = e.get("payer_did")
                contract.accept = {
                    "type": "accept",
                    "contract": cid,
                    "ref": (offer or {}).get("id"),
                    "from": accepter,
                    "_ts": e.get("accept_ts"),
                    "_synthetic": True,
                }

            payer = e.get("payer_did")
            payee = e.get("payee_did")

            n_locks = max(_int(e.get("lock_count")), 1 if state == "locked" else 0)
            if n_locks:
                contract.locks = [
                    {"type": "lock", "from": payer, "_synthetic": True}
                    for _ in range(n_locks)
                ]

            n_reveals = max(
                _int(e.get("reveal_count")), 1 if state == "revealed" else 0
            )
            if n_reveals:
                contract.reveals = [
                    {"type": "reveal", "from": payee, "_synthetic": True}
                    for _ in range(n_reveals)
                ]

            n_refunds = max(
                _int(e.get("refund_count")), 1 if state == "refunded" else 0
            )
            if n_refunds:
                contract.refunds = [
                    {"type": "refund", "from": payer, "_synthetic": True}
                    for _ in range(n_refunds)
                ]

            if _int(e.get("cancel_count")):
                contract.cancels = [
                    {"type": "cancel", "from": None, "_synthetic": True}
                    for _ in range(_int(e.get("cancel_count")))
                ]

            if state in ("claimed", "receipted"):
                # The state derives from receipts[0].outcome — restore the
                # published outcome so the state property reproduces exactly.
                outcome = state if state in KNOWN_OUTCOMES else None
                n_receipts = max(_int(e.get("receipt_count")), 1)
                contract.receipts = [
                    {"type": "receipt", "from": None, "outcome": outcome, "_synthetic": True}
                    for _ in range(n_receipts)
                ]
            elif _int(e.get("receipt_count")):
                # refunded/cancelled states derive from refund/cancel frames
                # (already synthesized above); receipts are rebuilt only when
                # the snapshot actually published some, with the published
                # outcome — so deals_refunded_as_payer attribution stays
                # identical to a live-observed contract of the same shape.
                contract.receipts = [
                    {
                        "type": "receipt",
                        "from": None,
                        "outcome": e.get("receipt_outcome"),
                        "_synthetic": True,
                    }
                    for _ in range(_int(e.get("receipt_count")))
                ]

            if _int(e.get("heartbeat_count")):
                contract.heartbeats = [
                    {"type": "heartbeat", "from": None, "_synthetic": True}
                    for _ in range(_int(e.get("heartbeat_count")))
                ]

            oid = (contract.offer or {}).get("id")
            if oid and oid == cid and cid in accepted_offer_ids:
                contract.offer_linked_elsewhere = True

            self._contracts[cid] = contract
            restored += 1

        # Offer-id → contract-id aliases; accepted contracts win (they are
        # keyed by the contract id later frames reference).
        for cid, contract in self._contracts.items():
            oid = (contract.offer or {}).get("id")
            if oid and oid != cid:
                self._offer_id_to_contract[oid] = cid
        return restored

    # Convenience properties
    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def total_frames(self) -> int:
        return self._total_frames
