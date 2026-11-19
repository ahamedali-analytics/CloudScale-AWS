# CloudScale development and verification (macOS)

## What is implemented

- **POST /jobs** validates JSON records, stores input in S3, writes a DynamoDB job, and sends an SQS message.
- **SQS worker** processes one message at a time, stores the result, and returns `batchItemFailures` so AWS can retry unsuccessful messages.
- **GET /jobs/{jobId}** reads job status and finished results.
- The frontend checks job status automatically for up to approximately 3 minutes after submission, then allows manual refresh.

These behaviors are implemented in source code. They are **not proof of deployment or working AWS integration**.

## Local setup

```bash
cd ~/Downloads/CloudScale-AWS
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt pytest
python -m pytest tests -q
node --check frontend/app.js  # optional; requires Node.js
sam validate --lint           # requires AWS SAM CLI
sam build                     # requires AWS SAM CLI
```

All unit tests use mocks and placeholder AWS identifiers. Running them does not require AWS credentials or deploy AWS resources.

`sam local invoke` requires Docker and, for the real submission handler, **real or emulated DynamoDB/S3/SQS services**. Docker alone does not emulate those AWS services.

## Deploy only after verifying the AWS account and costs

```bash
aws sts get-caller-identity
sam deploy --guided
```

Check stack name, region, IAM policies, billable resources, and existing AWS resources before confirming deployment. The API currently permits anonymous access and wildcard CORS, so do not expose it publicly with production or sensitive data without adding authorization and tighter CORS.

## End-to-end validation checklist

1. Submit a valid JSON record array to `POST /jobs` and expect HTTP 202 with a job ID.
2. Confirm an S3 input object, DynamoDB job record, and SQS message are created.
3. Confirm the worker changes job state to `PROCESSING`, produces an S3 result, and sets `COMPLETED`.
4. Call `GET /jobs/{jobId}` and confirm the returned result matches the original input.
5. Submit invalid inputs and verify correct HTTP 400/413 responses.
6. Trigger a controlled worker failure; confirm retries and eventual DLQ routing after the configured receive threshold. Confirm job status remains consistent.
7. Review CloudWatch logs, record latency and throughput under a few controlled workloads, and track AWS charges.
8. Clean up test stacks and their persistent resources when done.

## Notes on reliability

- The worker's `MAX_RECEIVE_COUNT` constant must match `JobQueue.RedrivePolicy.maxReceiveCount` in `template.yaml` (currently 5).
- SQS provides at-least-once delivery. Further hardening should add idempotency, safe job state transitions, and cleanup/compensation if storage succeeds but message enqueueing fails.
- A single job is processed within one Lambda; the project demonstrates queue-based concurrent jobs but does not split one job across multiple Lambda workers.
- Live AWS execution, security, performance, and cost are **not verified** by unit tests or `sam build` alone.
