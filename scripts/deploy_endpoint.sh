#!/usr/bin/env bash
# Deploy a new model version to the SageMaker inference endpoint.
# Uses blue/green via endpoint config swap.
set -euo pipefail

ENV="${1:-}"
MODEL_S3_URI="${2:-}"

if [[ -z "$ENV" || -z "$MODEL_S3_URI" ]]; then
    echo "Usage: $0 <env> <s3://bucket/path/to/model.tar.gz>"
    exit 1
fi

cd infra/terraform
ENDPOINT_NAME=$(terraform output -raw endpoint_name)
MODEL_NAME=$(terraform output -raw endpoint_name)-$(date +%s)
cd -

echo "=== Deploying $MODEL_S3_URI to $ENDPOINT_NAME ==="

# 1. Create new SageMaker Model
echo "Step 1/3: Creating new model '$MODEL_NAME'..."
aws sagemaker create-model \
    --model-name "$MODEL_NAME" \
    --execution-role-arn "$(cd infra/terraform && terraform output -raw sagemaker_inference_role_arn 2>/dev/null || echo '')" \
    --primary-container "Image=683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1,ModelDataUrl=$MODEL_S3_URI,Environment={SAGEMAKER_PROGRAM=predictor.py,SAGEMAKER_SUBMIT_DIRECTORY=/opt/ml/code}"

# 2. Create new endpoint config
NEW_CONFIG_NAME="${ENDPOINT_NAME}-config-$(date +%s)"
echo "Step 2/3: Creating endpoint config '$NEW_CONFIG_NAME'..."
aws sagemaker create-endpoint-config \
    --endpoint-config-name "$NEW_CONFIG_NAME" \
    --production-variants "VariantName=AllTraffic,ModelName=$MODEL_NAME,InitialInstanceCount=2,InstanceType=ml.m5.xlarge,InitialVariantWeight=1.0"

# 3. Update endpoint (this is blue/green -- SageMaker keeps old instances serving
#    until new ones are InService)
echo "Step 3/3: Updating endpoint (blue/green rollout)..."
aws sagemaker update-endpoint \
    --endpoint-name "$ENDPOINT_NAME" \
    --endpoint-config-name "$NEW_CONFIG_NAME"

echo "Rollout started. Monitor with:"
echo "  aws sagemaker describe-endpoint --endpoint-name $ENDPOINT_NAME"
echo "  Expected: EndpointStatus transitions Updating -> InService (~5-10 min)"
