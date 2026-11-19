"""SQS worker contract tests: successful and failed messages must be reported correctly."""
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

WORKER_DIR = Path(__file__).resolve().parents[1] / "backend" / "worker"
sys.path.insert(0, str(WORKER_DIR))
spec = importlib.util.spec_from_file_location("cloudscale_worker_app", WORKER_DIR / "app.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def sqs_event(receive_count=1, body=None):
    return {
        "Records": [{
            "messageId": "message-1",
            "body": json.dumps({"jobId": "job-1", "inputKey": "jobs/job-1/input.json"}) if body is None else body,
            "attributes": {"ApproximateReceiveCount": str(receive_count)},
        }]
    }


@pytest.fixture(autouse=True)
def fake_services(monkeypatch):
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = {
        "Body": io.BytesIO(json.dumps([{"a": 1}, {"a": 3}]).encode("utf-8"))
    }
    fake_table = MagicMock()
    monkeypatch.setattr(worker, "s3", fake_s3)
    monkeypatch.setattr(worker, "TABLE", fake_table)
    return fake_s3, fake_table


def test_success_acknowledges_message(fake_services):
    s3, table = fake_services
    assert worker.lambda_handler(sqs_event(), None) == {"batchItemFailures": []}
    s3.put_object.assert_called_once()
    assert table.update_item.call_count == 2
    assert 'COMPLETED' in str(table.update_item.call_args)


def test_transient_failure_retries_without_marking_failed(fake_services):
    s3, table = fake_services
    s3.get_object.side_effect = RuntimeError("temporary S3 failure")
    assert worker.lambda_handler(sqs_event(receive_count=2), None) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}]
    }
    assert table.update_item.call_count == 2
    last_update = str(table.update_item.call_args)
    assert 'RETRYING' in last_update
    assert 'FAILED' not in last_update


def test_fifth_failure_marks_failed_and_requests_dlq_redrive(fake_services):
    s3, table = fake_services
    s3.get_object.side_effect = RuntimeError("permanent S3 failure")
    assert worker.lambda_handler(sqs_event(receive_count=5), None) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}]
    }
    assert 'FAILED' in str(table.update_item.call_args)


def test_invalid_message_is_reported_as_failed(fake_services):
    assert worker.lambda_handler(sqs_event(body='not-json'), None) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}]
    }
    fake_services[1].update_item.assert_not_called()


def test_status_update_failure_is_not_acknowledged(fake_services):
    s3, table = fake_services
    table.update_item.side_effect = RuntimeError('DynamoDB unavailable')
    assert worker.lambda_handler(sqs_event(), None) == {
        "batchItemFailures": [{"itemIdentifier": "message-1"}]
    }


def test_mixed_batch_only_retries_failed_message(fake_services):
    s3, table = fake_services
    event = sqs_event()
    event['Records'].append({
        'messageId': 'message-2',
        'body': 'not-json',
        'attributes': {'ApproximateReceiveCount': '1'},
    })
    assert worker.lambda_handler(event, None) == {
        'batchItemFailures': [{'itemIdentifier': 'message-2'}]
    }
