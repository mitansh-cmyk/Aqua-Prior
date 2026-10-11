#!/usr/bin/env bash
# One-command deploy. Needs: AWS CLI configured, AWS SAM CLI, Docker (for building strands-agents) or use --use-container off.
set -e
cd "$(dirname "$0")"
sam build
sam deploy --guided            # first time; afterwards: sam deploy
BUCKET=$(aws cloudformation describe-stacks --stack-name "${STACK:-aquaprior}" --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text)
aws s3 cp ../data/zones.json  "s3://$BUCKET/processed/zones.json"
aws s3 cp ../data/meta.json   "s3://$BUCKET/processed/meta.json"
aws s3 cp ../data/wells.json  "s3://$BUCKET/processed/wells.json"
echo "Done. Put the ApiUrl output into frontend/.env as VITE_API_URL"
