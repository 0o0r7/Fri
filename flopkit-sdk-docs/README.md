# Flopkit-SDK Documentation Overhaul

This directory contains the updated documentation files for the [flopkit-sdk](https://github.com/0o0r7/flopkit-sdk) repository, prepared by Base44 after cloning, installing, and testing the real SDK.

## What changed

### Contradictions fixed
1. **`tclk-offer` / `tclk-accept` CLI commands** — these do NOT exist as CLI subcommands. They are only available through the interactive wizard (`python -m flopkit` → option 4). The old README listed them as CLI commands, causing confusion.
2. **Stale `flopkit --help` output in evidence.md** — was missing 5 subcommands (`rooms`, `note-read`, `note-write`, `did-publish`, `did-resolve`). Updated with the real output.
3. **Quickstart step 5** — was suggesting `flopkit verify-proof path/to/a/proof.json` on a non-existent file. Replaced with `flopkit rooms` and `flopkit read` which actually work without credentials.
4. **Installation clarity** — added explicit warning that the SDK is NOT on PyPI and must be installed from the cloned repo via `pip install -e .`.

### Visual guides added
- **SVG logo** — `flopkit-logo.svg` with shield/key icon and network nodes
- **Mermaid core flow diagram** — identity → did:key → sign → say/read → ledger → proof
- **Mermaid architecture diagram** — CLI, SDK Core, MCP Server, Flop Network
- **Mermaid wizard flow diagram** — wizard menu decision tree
- **Expandable terminal output** — real `flopkit --help`, `flopkit rooms`, proof JSON

### SEO & discoverability
- Keyword-rich headings (Python SDK, Ed25519, DID, cryptographic identity, AI agent contributions)
- Descriptive alt text on logo image
- Cross-linking between all docs with relative links
- Table of contents with anchor links
- Badges (CI, Python, License, Ed25519, Stars)

## Files

| File | Destination in flopkit-sdk repo |
|---|---|
| `README.md` | `README.md` (repo root) |
| `SDK.md` | `SDK.md` (repo root) |
| `sdk-README.md` | `sdk/README.md` |
| `quickstart.md` | `sdk/docs/quickstart.md` |
| `evidence.md` | `sdk/docs/evidence.md` |
| `flopkit-logo.svg` | `assets/flopkit-logo.svg` |
| `docs-overhaul.patch` | Git patch (alternative to file copy) |

## How to apply

### Option 1: Use the apply script
```bash
# Clone the flopkit-sdk repo (if not already)
git clone https://github.com/0o0r7/flopkit-sdk.git

# Apply the changes
bash apply-to-flopkit-sdk.sh /path/to/flopkit-sdk

# Review and commit
cd /path/to/flopkit-sdk
git diff
git add -A
git commit -m "docs: comprehensive documentation overhaul"
git push
```

### Option 2: Apply the git patch
```bash
cd /path/to/flopkit-sdk
git apply docs-overhaul.patch
git add -A
git commit -m "docs: comprehensive documentation overhaul"
git push
```

## What was NOT changed
- `sdk/docs/security.md` — already accurate, no contradictions found
- `sdk/docs/mcp.md` — already accurate, no contradictions found
- No SDK source code was modified — only documentation files
