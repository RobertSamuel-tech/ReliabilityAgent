#!/bin/bash
set -euo pipefail
PROJECT=${GOOGLE_CLOUD_PROJECT:?"Set GOOGLE_CLOUD_PROJECT"}
REGION=${GOOGLE_CLOUD_LOCATION:-us-central1}
SERVICE_NAME="reliability-agent"
IMAGE="gcr.io/${PROJECT}/${SERVICE_NAME}"

gcloud services enable cloudbuild.googleapis.com run.googleapis.com aiplatform.googleapis.com
gcloud builds submit --tag ${IMAGE}
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE} \
  --region ${REGION} \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --set-env-vars "GOOGLE_CLOUD_LOCATION=${REGION}" \
  --set-env-vars "GEMINI_MODEL=gemini-2.0-flash" \
  --memory 1Gi --cpu 2 --timeout 300 --min-instances 0 --max-instances 10
