#!/usr/bin/env bash
# Bootstrap local AWS resources in LocalStack for development.
# Run after `make compose-up`.
set -euo pipefail

AWS_ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PREFIX="${LOCAL_PREFIX:-feature-platform-local}"

AWS="aws --endpoint-url $AWS_ENDPOINT --region $AWS_REGION"

echo "=== Waiting for LocalStack ==="
for _ in {1..30}; do
    if curl -sf "$AWS_ENDPOINT/_localstack/health" | grep -q '"kinesis": "available"'; then
        break
    fi
    sleep 2
done

echo "=== Creating Kinesis stream ==="
$AWS kinesis create-stream \
    --stream-name "${PREFIX}-user-events" \
    --shard-count 1 2>/dev/null || echo "  (already exists)"

echo "=== Creating DynamoDB state table ==="
$AWS dynamodb create-table \
    --table-name "${PREFIX}-user-state" \
    --attribute-definitions AttributeName=user_id,AttributeType=S \
    --key-schema AttributeName=user_id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST 2>/dev/null || echo "  (already exists)"

echo "=== Creating S3 buckets ==="
for bucket in feature-store-offline artifacts data-capture monitor-reports; do
    $AWS s3 mb "s3://${PREFIX}-${bucket}" 2>/dev/null || echo "  (${bucket} already exists)"
done

echo "=== Bootstrap complete ==="
$AWS kinesis list-streams
$AWS dynamodb list-tables
$AWS s3 ls
