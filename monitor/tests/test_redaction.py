import pytest

from monitor.redaction import redact


@pytest.mark.parametrize(
    ("source", "secret"),
    [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ('request={"api_key":"sk-example123"}', "sk-example123"),
        ("password=hunter2 next=value", "hunter2"),
        ("bot 123456789:AAExampleTelegramToken_123456789", "AAExampleTelegramToken"),
        ("https://alice:supersecret@example.test/path", "supersecret"),
    ],
)
def test_recognizable_credentials_are_redacted(source, secret):
    result = redact(source)
    assert secret not in result
    assert "[REDACTED]" in result


def test_non_secret_log_content_is_preserved():
    assert redact("2026-01-01 job completed") == "2026-01-01 job completed"

