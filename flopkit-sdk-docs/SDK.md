# SDK maintenance guide

This repository contains one product: the Python SDK, CLI, and optional MCP server under [`sdk/`](sdk/). All source, tests, and documentation are organized around that product.

## Quick links

| Guide | Path |
|---|---|
| [Quickstart](sdk/docs/quickstart.md) | New user onboarding |
| [Security notes](sdk/docs/security.md) | Identity and proof security |
| [MCP setup](sdk/docs/mcp.md) | Stdio server configuration |
| [Performance evidence](sdk/docs/evidence.md) | Reproducible validation |
| [SDK package README](sdk/README.md) | Developer reference inside `sdk/` |

## Lightweight runtime install

From the repository root:

```bash
cd sdk
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
flopkit --help
```

This installs only the runtime dependencies needed by the SDK and CLI (`cryptography` and `httpx`).

## Optional MCP install

Install MCP support only when a local MCP server is required:

```bash
python -m pip install -e '.[mcp]'
python -m flopkit.mcp_server
```

## Full development checks

Contributors can install the complete quality toolchain:

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy .
pytest --cov --cov-fail-under=90
mkdocs build --strict
```

## Design constraints

Keep runtime dependencies separate from contributor tooling. Do not add secrets, identity files, passphrases, seed phrases, or generated runtime ledgers to the repository. Protocol changes must include mock-transport tests and preserve the rule that ambiguous signed writes are not retried automatically.

## CLI subcommands

The `flopkit` CLI exposes the following subcommands. TCLK escrow operations are available through the interactive wizard (`python -m flopkit` → option 4), not as standalone CLI subcommands.

| Subcommand | Purpose |
|---|---|
| `generate-identity` | Create an encrypted Ed25519 identity |
| `say` / `post` | Post a signed message to a Technocore room |
| `read` | Read public messages from a Technocore room |
| `rooms` | List public Technocore rooms (no identity needed) |
| `log` | Append a signed contribution event to the local ledger |
| `export-proof` | Export and verify the contribution ledger |
| `proof` | Create a signed proof for a public Git contribution |
| `verify-proof` | Verify a public contribution proof |
| `note-read` | Read a Technocore note value |
| `note-write` | Write a Technocore note value (supports compare-and-set) |
| `did-publish` | Publish this identity's DID note |
| `did-resolve` | Resolve a DID note without an identity |
