import json
import os
from datetime import datetime, timezone
import boto3
from processor import process_records

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
TABLE = dynamodb.Table(os.environ["JOBS_TABLE"])
BUCKET = os.environ["DATA_BUCKET"]
MAX_RECEIVE_COUNT = 5  # Must match JobQueue.RedrivePolicy.maxReceiveCount in template.yaml.


def update_job(job_id, status, **extra):
    names = {"#status": "status"}
    values = {
        ":status": status,
        ":updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    assignments = ["#status = :status", "updatedAt = :updatedAt"]
    for i, (key, value) in enumerate(extra.items()):
        name_token, value_token = f"#k{i}", f":v{i}"
        names[name_token] = key
        values[value_token] = value
        assignments.append(f"{name_token} = {value_token}")
    TABLE.update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="attribute_exists(jobId)",
    )


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        job_id = None
        try:
            message = json.loads(record["body"])
            job_id, input_key = message["jobId"], message["inputKey"]
            update_job(job_id, "PROCESSING")
            obj = s3.get_object(Bucket=BUCKET, Key=input_key)
            records = json.loads(obj["Body"].read().decode("utf-8"))
            result = process_records(records)
            result_key = f"jobs/{job_id}/result.json"
            s3.put_object(
                Bucket=BUCKET, Key=result_key,
                Body=json.dumps(result).encode("utf-8"),
                ContentType="application/json",
            )
            update_job(
                job_id, "COMPLETED", resultKey=result_key,
                resultSummary={"recordCount": result["recordCount"], "fieldCount": result["fieldCount"]},
            )
        except Exception as exc:
            print("Job processing failed", {"messageId": message_id, "error": str(exc)})
            receive_count = int((record.get("attributes") or {}).get("ApproximateReceiveCount", "1"))
            if job_id:
                try:
                    if receive_count >= MAX_RECEIVE_COUNT:
                        update_job(
                            job_id, "FAILED",
                            errorMessage="Processing failed after repeated attempts; inspect worker logs.",
                        )
                    else:
                        update_job(job_id, "RETRYING", retryCount=receive_count)
                except Exception as update_exc:
                    print("Unable to update failed job", {"jobId": job_id, "error": str(update_exc)})
            failures.append({"itemIdentifier": message_id})

    # Required by the SQS event source's ReportBatchItemFailures setting.
    # Omitting this response would acknowledge failed messages and prevent retries/DLQ redrive.
    return {"batchItemFailures": failures}
