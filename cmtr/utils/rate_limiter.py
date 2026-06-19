import time
import threading
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter per source."""

    def __init__(self, requests_per_second: float, source: str = ""):
        self.source = source
        self.min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            wait_time = self.min_interval - elapsed
            if wait_time > 0:
                logger.debug("[%s] rate limit wait %.2fs", self.source, wait_time)
                time.sleep(wait_time)
            self._last_call = time.monotonic()


# Pre-configured limiters per source (safe conservative values)
LIMITERS = {
    "uniprot": RateLimiter(requests_per_second=3.0, source="uniprot"),
    "pdb": RateLimiter(requests_per_second=5.0, source="pdb"),
    "chembl": RateLimiter(requests_per_second=1.0, source="chembl"),
    "opentargets": RateLimiter(requests_per_second=2.0, source="opentargets"),
    "pubmed": RateLimiter(requests_per_second=3.0, source="pubmed"),  # requires API key for 10/s
}
