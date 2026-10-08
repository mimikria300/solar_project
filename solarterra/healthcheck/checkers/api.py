import time
from datetime import datetime, timezone
from django.test import Client
from .base import BaseChecker, ComponentResult, Status
import logging


logger = logging.getLogger('solarterra.healthcheck.api')


_SLOW_THRESHOLD_SEC = 10.0


class ApiChecker(BaseChecker):
    """Checker for api."""

    KEY_GET = [
        "/",
        "/data_info",
        "/missions",
        "/variables",
    ]

    NON_KEY_GET = [
        "/upload_info/00000000-0000-0000-0000-000000000000",
        "/variable_info/00000000-0000-0000-0000-000000000000",
        "/system_data",
        "/logs",
    ]

    TEST_MISSION_NAME = "INTERBALL>Interball"
    TEST_START_TIME = "1998-03-01 00:00:00"
    TEST_END_TIME = "1998-03-31 00:00:00"
    TEST_VAR_IDS = [
        "75f92f8b-44e6-416e-b2e1-270d8187bff9",
        "5b1cc752-de33-4c1d-9e0c-369c2eeff549",
    ]

    def check(self) -> ComponentResult:
        client = Client(HTTP_HOST="127.0.0.1")
        now = datetime.now(timezone.utc)

        key_errors = []
        non_key_errors = []
        slow_endpoints = []

        # GET - key
        for endpoint in self.KEY_GET:
            code, error, elapsed = self._probe_get(client, endpoint)
            logger.info(f"GET {endpoint}: {code}-{error}-{elapsed:.4f}s")
            if code >= 500 or error:
                reason = error if error else f"HTTP {code}"
                key_errors.append(f"{endpoint} -> ({reason})")

        # GET - non-key
        for endpoint in self.NON_KEY_GET:
            code, error, elapsed = self._probe_get(client, endpoint)
            logger.info(f"GET {endpoint}: {code}-{error}-{elapsed:.4f}s")
            if code >= 500 or error:
                reason = error if error else f"HTTP {code}"
                non_key_errors.append(f"{endpoint} -> ({reason})")

        # POST - key
        self._setup_session(client)

        base_post = {
            "variables": self.TEST_VAR_IDS,
            "ts_start": self.TEST_START_TIME,
            "ts_end": self.TEST_END_TIME,
        }

        post_scenarios = [
            ("/plot", "plot without validation", {**base_post}),
            ("/plot", "plot with validation", {**base_post, "validate": "on"}),
            ("/export", "export plain text", {**base_post, "export_format": "plain_text"}),
            ("/export", "export raw cdf", {**base_post, "export_format": "raw_cdf"}),
        ]

        for endpoint, name, data in post_scenarios:
            code, error, elapsed = self._probe_post(client, endpoint, data)
            logger.info(f"POST {endpoint} [{name}]: {code}-{error}-{elapsed:.4f}s")

            if code >= 500 or error:
                reason = error if error else f"HTTP {code}"
                key_errors.append(f"{endpoint} [{name}] -> ({reason})")
            elif elapsed > _SLOW_THRESHOLD_SEC:
                slow_endpoints.append(f"{endpoint} [{name}] completed in {elapsed:.4f}s")

        if key_errors:
            return ComponentResult(
                name="api",
                status=Status.DOWN,
                last_check=now,
                details="; ".join(key_errors),
            )

        problems = non_key_errors + slow_endpoints
        if problems:
            return ComponentResult(
                name="api",
                status=Status.DEGRADED,
                last_check=now,
                details="; ".join(problems),
            )

        return ComponentResult(
            name="api",
            status=Status.OK,
            last_check=now,
        )

    @staticmethod
    def _probe_get(client, endpoint):
        """Return (status_code, error_string, elapsed_seconds)."""

        try:
            start = time.monotonic()
            response = client.get(endpoint)
            elapsed = time.monotonic() - start
            return response.status_code, None, elapsed
        except Exception as e:
            logger.error(f"Probe GET failed: {endpoint}", exc_info=True)
            return 0, str(e), 0

    @staticmethod
    def _probe_post(client, endpoint, data):
        """Return (status_code, error_string, elapsed_seconds)."""

        try:
            start = time.monotonic()
            response = client.post(endpoint, data)
            elapsed = time.monotonic() - start
            return response.status_code, None, elapsed
        except Exception as e:
            logger.error(f"Probe POST failed: {endpoint}", exc_info=True)
            return 0, str(e), 0

    def _setup_session(self, client):
        session = client.session
        session["selected_missions"] = [self.TEST_MISSION_NAME]
        session.save()
