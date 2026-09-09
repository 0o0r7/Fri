# FRI — Flop Reputation Index — Project Context

This file holds cross-phase context that all agents work from.

## SDK dependency: flopkit

Repo: https://github.com/0o0r7/flopkit-sdk
Author: 0o0r7 (the project owner)
License: MIT
Local clone: /home/z/my-project/flopkit-sdk

FRI uses `flopkit` as a core dependency. It replaces our hand-rolled
`collector/fetch.py` and gives us production-grade:

- `flopkit.TechnocoreClient` — HTTP client with retry, rate-limit handling,
  422 (DuplicateMessageError), 429 (RateLimitedError), 409 (NoteConflictError)
  exceptions, signed writes, note CAS, DID note publishing, DID resolution
- `flopkit.did_note_path(did)` → (shard, key) for the sharded /kv/did-<shard>/<key>
  convention
- `flopkit.did_to_public_key(did)` → Ed25519PublicKey for offline verification
- `flopkit.verify_signature(did, payload, signature)` → bool
- `flopkit.message_payload(room, nonce, text)` → (normalized_text, payload_bytes)
- `flopkit.normalize_message(text)` — the exact single-line sweep Technocore uses
- `flopkit.ContributionLedger` + `flopkit.proofs` — signed contribution proofs
  bound to git commits (`technocore-contribution-proof-v1` schema)
- `flopkit.TCLKManager` — basic TCLK offer posting (we'll extend for full frames)

## User's DID (for FRI service identity, Phase 6)

`did:key:z6MkkQU8p82GRFeBaifwCJhpfdYeVBfn4xTAnMA6ounPNXmP`

- Created via flopkit, identity.pem stored offline on the user's Windows machine
- Profile synced to /kv/did-4f/541151fd42c677 with bio
  "Senior Ecosystem Architect | Exploring the Flop Network"
- First signed message posted to /r/technocore (SDK announcement)
- First TCLK offer posted to /r/tclk-offers (nonce 1eb01dafd01583d2)

This DID may be used as the FRI service identity for Phase 6 publication
(signed intro post, DID note update with `fri:` capability token).
The user retains the private key; FRI never touches it. Phase 6 sign-off
will require the user to run a CLI command on their machine.

## Hosting plan

- Frontend: Cloudflare Pages or Vercel (user has GitHub Education benefits)
- Collector cron: GitHub Actions (every 2h)
- Domain: TBD — user has GitHub Education domain credits available
- GitHub repo: user's personal GitHub (0o0r7) — they have a GitHub business page too

## What does NOT change

- FRI is still read-only through Phase 5
- FRI is still independent community infrastructure, not Flop Labs official
- No private keys on the server ever
- All scoring is transparent and documented
