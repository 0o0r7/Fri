#!/usr/bin/env bash
# Apply the flopkit-sdk documentation overhaul to your local clone.
# Usage: bash apply-to-flopkit-sdk.sh /path/to/flopkit-sdk
set -euo pipefail

REPO="${1:-$(pwd)/flopkit-sdk}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$REPO/.git" ]; then
  echo "Error: $REPO is not a git repository"
  echo "Usage: bash apply-to-flopkit-sdk.sh /path/to/flopkit-sdk"
  exit 1
fi

echo "Applying documentation overhaul to $REPO ..."

# Copy files
cp "$SCRIPT_DIR/README.md"          "$REPO/README.md"
cp "$SCRIPT_DIR/SDK.md"             "$REPO/SDK.md"
cp "$SCRIPT_DIR/sdk-README.md"      "$REPO/sdk/README.md"
cp "$SCRIPT_DIR/quickstart.md"      "$REPO/sdk/docs/quickstart.md"
cp "$SCRIPT_DIR/evidence.md"        "$REPO/sdk/docs/evidence.md"
mkdir -p "$REPO/assets"
cp "$SCRIPT_DIR/flopkit-logo.svg"   "$REPO/assets/flopkit-logo.svg"

echo "Done. Review with: cd $REPO && git diff"
echo "Commit with:  cd $REPO && git add -A && git commit -m 'docs: comprehensive documentation overhaul'"
