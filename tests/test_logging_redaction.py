import logging

from backend.app.core.logging_config import SensitiveDataRedactionFilter


def test_mongodb_connection_string_password_is_masked_in_log_line(caplog):
    logger = logging.getLogger("test.mongo.redaction")
    redaction_filter = SensitiveDataRedactionFilter()
    logger.addFilter(redaction_filter)
    url = (
        "mongodb+srv://testuser:not-a-real-secret"
        "@cluster.example.test/traffic_ai"
    )

    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("Connecting to MongoDB at %s", url)
    finally:
        logger.removeFilter(redaction_filter)

    assert "mongodb://REDACTED" in caplog.text
    assert "cluster.example.test" not in caplog.text
    assert "not-a-real-secret" not in caplog.text


def test_query_token_redaction_stays_unquoted_and_structured_token_is_redacted():
    redactor = SensitiveDataRedactionFilter()

    url = redactor.redact("GET /api/stream/cam1?token=top-secret HTTP/1.1")
    assert "token=REDACTED" in url
    assert 'token="REDACTED"' not in url
    assert "top-secret" not in url

    structured = redactor.redact('{"token":"top-secret"}')
    assert structured == '{"token":"REDACTED"}'


def test_bearer_jwt_and_password_hash_arguments_are_redacted(caplog):
    logger = logging.getLogger("test.mongo.redaction.jwt")
    redaction_filter = SensitiveDataRedactionFilter()
    logger.addFilter(redaction_filter)
    jwt = "eyJhbGciOiJIUzI1NiJ9.payload.signature"
    password_hash = "$2b$12$synthetic-hash-value"

    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("Authorization: Bearer %s password_hash=%s", jwt, password_hash)
    finally:
        logger.removeFilter(redaction_filter)

    assert "Bearer REDACTED" in caplog.text
    assert "REDACTED\"" in caplog.text
    assert jwt not in caplog.text
    assert password_hash not in caplog.text
