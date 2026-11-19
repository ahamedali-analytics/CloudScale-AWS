"""Safe, non-production AWS environment for mocked tests."""
import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("JOBS_TABLE", "cloudscale-test-jobs")
os.environ.setdefault("DATA_BUCKET", "cloudscale-test-bucket")
os.environ.setdefault("JOB_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/cloudscale-test")
