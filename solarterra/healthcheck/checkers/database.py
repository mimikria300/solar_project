import time
from datetime import datetime, timezone
from django.db import connection
from .base import BaseChecker, ComponentResult, Status
import logging


logger = logging.getLogger('solarterra.healthcheck.database')


_SLOW_THRESHOLD_SEC = 0.5


class DatabaseChecker(BaseChecker):
    """Checker for database."""

    def check(self) -> ComponentResult:
        now = datetime.now(timezone.utc)
        try:
            time_test = self._ping()
        except Exception as e:
            logger.error(f"Test request failed", exc_info=True)
            return ComponentResult(
                name="database",
                status=Status.DOWN,
                last_check=now,
                details=str(e),
            )

        status = Status.OK if time_test < _SLOW_THRESHOLD_SEC else Status.DEGRADED

        return ComponentResult(
            name="database",
            status=status,
            last_check=now,
            details=f"test request time: {time_test:.4f}s",
        )

    @staticmethod
    def _ping():
        start = time.monotonic()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return time.monotonic() - start
