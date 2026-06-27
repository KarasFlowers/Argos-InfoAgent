import json

import structlog

from app.core.logging_config import redact_secrets, setup_logging


def test_redact_secrets_masks_sensitive_fields_and_nested_values():
    event = redact_secrets(
        None,
        "info",
        {
            "api_key": "sk-secret-value",
            "payload": {
                "Authorization": "Bearer abcdefghijklmnop",
                "nested": ["token ghp_abcdefghijklmnopqrstuvwxyz", "plain text"],
            },
            "message": "using sk-abcdefghijklmnopqrstuvwxyz for request",
        },
    )

    rendered = str(event)
    assert "sk-secret-value" not in rendered
    assert "abcdefghijklmnop" not in rendered
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in rendered
    assert event["api_key"] == "***"
    assert event["payload"]["Authorization"] == "***"
    assert event["payload"]["nested"][0] == "token ***"
    assert event["message"] == "using sk-*** for request"


def test_setup_logging_redacts_json_output(capsys):
    setup_logging(json_output=True)
    logger = structlog.get_logger("tests.redaction")

    logger.info(
        "provider call failed",
        api_key="sk-abcdefghijklmnopqrstuvwxyz",
        headers={"Authorization": "Bearer abcdefghijklmnop"},
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert payload["api_key"] == "***"
    assert payload["headers"]["Authorization"] == "***"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in captured.err
    assert "abcdefghijklmnop" not in captured.err
