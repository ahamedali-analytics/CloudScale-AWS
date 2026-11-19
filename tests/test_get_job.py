"""GET /jobs/{jobId} status and result API tests, using mocked AWS services."""
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

GET_PATH = Path(__file__).resolve().parents[1] / "backend" / "get_job" / "app.py"
spec = importlib.util.spec_from_file_location("cloudscale_get_job_app", GET_PATH)
get_job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(get_job)


@pytest.fixture(autouse=True)
def fake_services(monkeypatch):
    table = MagicMock()
    s3 = MagicMock()
    monkeypatch.setattr(get_job, "TABLE", table)
    monkeypatch.setattr(get_job, "s3", s3)
    return table, s3


def event(job_id="job-1"):
    return {"pathParameters": {"jobId": job_id}}


def parsed(result):
    return result["statusCode"], json.loads(result["body"])


def test_missing_job_id(fake_services):
    status, body = parsed(get_job.lambda_handler({"pathParameters": None}, None))
    assert status == 400
    assert "error" in body


def test_unknown_job_returns_404(fake_services):
    table, _ = fake_services
    table.get_item.return_value = {}
    status, body = parsed(get_job.lambda_handler(event(), None))
    assert status == 404
    assert body["jobId"] == "job-1"


def test_queued_job_returns_metadata_without_s3_read(fake_services):
    table, s3 = fake_services
    table.get_item.return_value = {"Item": {"jobId": "job-1", "status": "QUEUED", "recordCount": 3}}
    status, body = parsed(get_job.lambda_handler(event(), None))
    assert status == 200
    assert body["status"] == "QUEUED"
    assert body["recordCount"] == 3
    s3.get_object.assert_not_called()


def test_completed_job_returns_results(fake_services):
    table, s3 = fake_services
    table.get_item.return_value = {"Item": {"jobId": "job-1", "status": "COMPLETED", "resultKey": "jobs/job-1/result.json"}}
    s3.get_object.return_value = {"Body": io.BytesIO(b'{"recordCount":3}')}
    status, body = parsed(get_job.lambda_handler(event(), None))
    assert status == 200
    assert body["result"]["recordCount"] == 3
    s3.get_object.assert_called_once()


def test_failed_job_returns_error(fake_services):
    table, _ = fake_services
    table.get_item.return_value = {"Item": {"jobId": "job-1", "status": "FAILED", "errorMessage": "exhausted retries"}}
    status, body = parsed(get_job.lambda_handler(event(), None))
    assert status == 200
    assert body["error"] == "exhausted retries"


def test_dynamodb_error_returns_500(fake_services):
    table, _ = fake_services
    table.get_item.side_effect = ClientError({"Error": {"Code": "InternalServerError", "Message": "bad"}}, "GetItem")
    status, body = parsed(get_job.lambda_handler(event(), None))
    assert status == 500
    assert "error" in body
