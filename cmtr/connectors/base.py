import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from cmtr.utils.rate_limiter import LIMITERS

logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CMTR/0.1 (cancer drug discovery research; contact: research@cmtr)"})


def _get_limiter(source: str):
    return LIMITERS.get(source)


@retry(
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def fetch_json(url: str, params: dict = None, source: str = "") -> dict:
    limiter = _get_limiter(source)
    if limiter:
        limiter.wait()
    resp = SESSION.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


@retry(
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def fetch_text(url: str, params: dict = None, source: str = "") -> str:
    limiter = _get_limiter(source)
    if limiter:
        limiter.wait()
    resp = SESSION.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.text
