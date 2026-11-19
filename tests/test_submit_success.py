"""Happy-path and oversized submission tests with mocked AWS services."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SUBMIT_PATH = Path(__file__).resolve().parents[1] / "backend" / "submit_job" / "app.py"
spec = importlib.util.spec_from_file_location("cloudscale_submit_success_app", SUBMIT_PATH)
submit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(submit)


@pytest.fixture(autouse=True)
def fake_services(monkeypatch):
    s3, sqs, table = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(submit, "s3", s3)
    monkeypatch.setattr(submit, "sqs", sqs)
    monkeypatch.setattr(submit, "TABLE", table)
    return s3, sqs, table


def test_valid_job_is_stored_and_enqueued(fake_services):
    s3, sqs, table = fake_services
    response = submit.lambda_handler({"body": json.dumps({"records": [{"a": 2}]})}, None)
    payload = json.loads(response["body"])
    assert response["statusCode"] == 202
    assert payload["status"] == "QUEUED"
    assert payload["jobId"]
    assert table.put_item.call_args.kwargs["Item"]["jobId"] == payload["jobId"]
    assert json.loads(sqs.send_message.call_args.kwargs["MessageBody"])["jobId"] == payload["jobId"]
    s3.put_object.assert_called_once()


def test_rejects_more_than_max_records_without_aws_writes(fake_services):
    s3, sqs, table = fake_services
    response = submit.lambda_handler({"body": json.dumps({"records": [{}] * (submit.MAX_RECORDS + 1)})}, None)
    assert response["statusCode"] == 413
    s3.put_object.assert_not_called()
    table.put_item.assert_not_called()
    sqs.send_message.assert_not_called()
