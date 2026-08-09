from cudaq_guard.crypto import redact_mapping


def test_sensitive_target_options_are_redacted() -> None:
    value = redact_mapping({"machine": "x", "api_token": "secret", "nested": {"password": "p"}})
    assert value["machine"] == "x"
    assert value["api_token"] == "<redacted>"
    assert value["nested"]["password"] == "<redacted>"
