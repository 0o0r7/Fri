"""Flop Reputation Index (FRI) collector package.

Extends the original TQR (Technocore Quality Rooms) collector with:
  - DID index (Phase 1)
  - Kibble detection (Phase 2)
  - TCLK deal-flow analytics (Phase 3)
  - Reputation scoring (Phase 4)

Each module ingests the same message stream independently. See README.md
for the architecture and roadmap.
"""

__version__ = "0.2.0-dev"
