#!/usr/bin/env bash
# Run drift detection against the latest production feature snapshot.
# Outputs a drift-report.json + exits with code 1 if drift detected.
set -euo pipefail

BASELINE_S3="${1:-}"
CURRENT_S3="${2:-}"
OUTPUT="${3:-./drift-report.json}"
PSI_THRESHOLD="${PSI_THRESHOLD:-0.25}"

if [[ -z "$BASELINE_S3" || -z "$CURRENT_S3" ]]; then
    echo "Usage: $0 <baseline_s3_uri> <current_s3_uri> [output_path]"
    echo "       PSI_THRESHOLD=0.15 $0 ... (override threshold)"
    exit 1
fi

mkdir -p /tmp/drift_check
aws s3 cp "$BASELINE_S3" /tmp/drift_check/baseline.parquet
aws s3 cp "$CURRENT_S3" /tmp/drift_check/current.parquet

features check-drift \
    --baseline-path /tmp/drift_check/baseline.parquet \
    --current-path /tmp/drift_check/current.parquet \
    --psi-threshold "$PSI_THRESHOLD" \
    --output-path "$OUTPUT"

# Exit non-zero if drift was detected (pipes into CI alert logic)
DRIFT=$(python3 -c "import json; print(json.load(open('$OUTPUT'))['any_drift'])")
if [[ "$DRIFT" == "True" ]]; then
    echo "DRIFT DETECTED -- see $OUTPUT"
    exit 1
fi

echo "No drift detected."
