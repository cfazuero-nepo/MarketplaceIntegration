"""Ticket 1: the temporary Marketplace ``state`` must not appear in application logs."""
import logging
import socket
import threading
import time

import pytest
import requests
import uvicorn
from uvicorn.config import LOGGING_CONFIG

import main
from conftest import add_session

STATE = "Ab3_dE6-gH9iJ2kL5mN8oP1qR4sT7uV0wX3yZ6aB9cD"


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            f"/api/marketplace/session/{STATE}",
            "/api/marketplace/session/[REDACTED]",
        ),
        (
            f"/api/marketplace/approve/{STATE}",
            "/api/marketplace/approve/[REDACTED]",
        ),
        (
            f"/api/marketplace/session/{STATE}?x=1",
            "/api/marketplace/session/[REDACTED]?x=1",
        ),
        (
            f"https://app.example.com/marketplace/signup?state={STATE}",
            "https://app.example.com/marketplace/signup?state=[REDACTED]",
        ),
        (f"/x?a=1&state={STATE}&b=2", "/x?a=1&state=[REDACTED]&b=2"),
        ("/healthz", "/healthz"),
        ("/marketplace/signup", "/marketplace/signup"),
    ],
)
def test_redact_state(text, expected):
    assert main.redact_state(text) == expected


def test_filter_is_installed_on_uvicorn_loggers():
    for name in ("uvicorn.access", "uvicorn.error"):
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, main.RedactStateFilter) for f in filters) == 1


def test_install_is_idempotent():
    main.install_log_redaction()
    main.install_log_redaction()
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, main.RedactStateFilter) for f in filters) == 1


def test_filter_redacts_uvicorn_access_record_format(caplog):
    # The exact call uvicorn's access logger makes for each request.
    logger = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger.propagate, old = True, logger.propagate
        try:
            logger.info(
                '%s - "%s %s HTTP/%s" %d',
                "203.0.113.5:1234",
                "GET",
                f"/api/marketplace/session/{STATE}",
                "1.1",
                200,
            )
        finally:
            logger.propagate = old

    assert STATE not in caplog.text
    assert "/api/marketplace/session/[REDACTED]" in caplog.text


def test_filter_redacts_dict_args_and_message():
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1,
        f"bad request to /api/marketplace/approve/{STATE} %(p)s",
        None, None,
    )
    record.args = {"p": f"?state={STATE}"}

    main.RedactStateFilter().filter(record)

    assert STATE not in record.getMessage()


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_uvicorn_access_log_never_contains_state(db):
    """Run the app under uvicorn with its default logging config, as in the Dockerfile."""
    state = add_session(db, STATE)
    port = _free_port()
    # Creating the Config applies uvicorn's logging dictConfig, as at start-up.
    config = uvicorn.Config(main.app, host="127.0.0.1", port=port, log_config=LOGGING_CONFIG)
    capture = _Capture()
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addHandler(capture)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start"

        base = f"http://127.0.0.1:{port}"
        assert requests.get(f"{base}/api/marketplace/session/{state}", timeout=5).status_code == 200
        assert requests.post(f"{base}/api/marketplace/approve/{state}", timeout=5).status_code == 403
        requests.get(f"{base}/healthz?state={state}", timeout=5)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        access_logger.removeHandler(capture)

    log = "\n".join(capture.lines)
    assert len(capture.lines) >= 3, log
    assert STATE not in log
    assert "/api/marketplace/session/[REDACTED]" in log
    assert "/api/marketplace/approve/[REDACTED]" in log
    # uvicorn's dictConfig replaced handlers but kept the filter.
    assert any(isinstance(f, main.RedactStateFilter) for f in access_logger.filters)
