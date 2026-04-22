#!/usr/bin/env bash
# Apply the Feast registry, running validation first.
set -euo pipefail

REPO="${1:-src/feast_repo}"

echo "=== Validating feature views ==="
python scripts/validate_feature_views.py "$REPO/feature_views/"

echo "=== Running feast plan (dry-run) ==="
cd "$REPO"
feast plan

read -p "Proceed with feast apply? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

feast apply
echo "Done."
