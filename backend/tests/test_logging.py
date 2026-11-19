import json
import logging

from app.core.logging import REDACTED, JsonFormatter, RedactSecretsFilter


def make_record(msg: str, fields: dict | None = None) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, None)
    if fields is not None:
        record.fields = fields
    return record


def test_secret_is_removed_from_message_and_fields():
    record = make_record("key is sk-123", {"header": "Bearer sk-123"})
    RedactSecretsFilter(["sk-123"]).filter(record)
    output = json.loads(JsonFormatter().format(record))
    assert "sk-123" not in json.dumps(output)
    assert output["msg"] == f"key is {REDACTED}"
    assert output["header"] == f"Bearer {REDACTED}"


def test_formatter_outputs_one_json_object_with_fields():
    output = json.loads(JsonFormatter().format(make_record("llm_call", {"tokens": 5})))
    assert output["msg"] == "llm_call"
    assert output["tokens"] == 5
    assert output["level"] == "INFO"
