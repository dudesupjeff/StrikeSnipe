import asyncio
import random
import time
from urllib.parse import quote
import httpx
from .config import settings

BASE = 'https://csfloat.com/api/v1'


RATE_LIMIT_FLOOR_SECONDS = 1.5     
RATE_LIMIT_MAX_BACKOFF_SECONDS = 120.0  

# csfloat can send out a few different headers to signal being rate limited so this just checks for some of the common ones I found and AI suggested...
# if you still proceed to be getting rate limited then they likely changed the headers again and you can add them to the list below or publish an issue on github and ill add them in for you. 
_REMAINING_HEADERS = ('x-ratelimit-remaining', 'x-rate-limit-remaining', 'ratelimit-remaining')
_LIMIT_HEADERS = ('x-ratelimit-limit', 'x-rate-limit-limit', 'ratelimit-limit')
_RESET_HEADERS = ('x-ratelimit-reset', 'x-rate-limit-reset', 'ratelimit-reset')


class RateLimitError(Exception):
    def __init__(self, retry_after: float):
        super().__init__('CSFloat rate limited')
        self.retry_after = retry_after

class CSFloatAPIError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f'HTTP {status}: {body[:800]}')
        self.status = status
        self.body = body


def unwrap(payload):
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        for key in ('data', 'listings', 'sales', 'items', 'history'):
            value = payload.get(key)
            if isinstance(value, list):
                return value, payload.get('cursor')
    return [], None


def _first_header(headers, names):
    for n in names:
        v = headers.get(n)
        if v is not None:
            return v
    return None


def _parse_rate_limit(headers):
    remaining_raw = _first_header(headers, _REMAINING_HEADERS)
    reset_raw = _first_header(headers, _RESET_HEADERS)
    limit_raw = _first_header(headers, _LIMIT_HEADERS)
    if remaining_raw is None or reset_raw is None:
        return None
    try:
        remaining = int(float(remaining_raw))
        reset_val = float(reset_raw)
        limit_val = int(float(limit_raw)) if limit_raw is not None else None
    except (TypeError, ValueError):
        return None

    if reset_val > 3600 * 24 * 2:
        seconds_until_reset = max(0.0, reset_val - time.time())
    else:
        seconds_until_reset = max(0.0, reset_val)
    return remaining, limit_val, seconds_until_reset


class _EndpointBucket:
    __slots__ = ('lock', 'next_allowed', 'blocked_until', 'last_remaining', 'last_limit')

    def __init__(self):
        self.lock = asyncio.Lock()
        self.next_allowed = 0.0
        self.blocked_until = 0.0
        self.last_remaining = None
        self.last_limit = None


class CSFloatClient:
    def __init__(self):
        headers = {'Accept': 'application/json', 'User-Agent': settings.user_agent}
        if settings.csfloat_api_key:
            headers['Authorization'] = settings.csfloat_api_key
        self.client = httpx.AsyncClient(base_url=BASE, timeout=settings.request_timeout_seconds, headers=headers)
        self._buckets = {}
        self.request_count = 0
        self.last_status = None
        self.rate_limit_snapshot = {}

    def _bucket(self, name):
        b = self._buckets.get(name)
        if b is None:
            b = _EndpointBucket()
            self._buckets[name] = b
        return b

    @property
    def blocked_until(self):
        return max((b.blocked_until for b in self._buckets.values()), default=0.0)

    async def _request(self, bucket_name, method, path, **kwargs):
        bucket = self._bucket(bucket_name)
        async with bucket.lock:
            wait = max(bucket.next_allowed - time.monotonic(), bucket.blocked_until - time.monotonic(), 0.0)
            if wait:
                await asyncio.sleep(wait)
            if settings.request_jitter_seconds > 0:
                await asyncio.sleep(random.uniform(0, settings.request_jitter_seconds))
            try:
                response = await self.client.request(method, path, **kwargs)
            except httpx.RequestError as exc:
                raise CSFloatAPIError(0, str(exc)) from exc
            self.request_count += 1
            self.last_status = response.status_code

            parsed = _parse_rate_limit(response.headers)
            if parsed:
                remaining, limit_val, seconds_until_reset = parsed
                bucket.last_remaining, bucket.last_limit = remaining, limit_val
                self.rate_limit_snapshot[bucket_name] = {'remaining': remaining, 'limit': limit_val}
                if remaining <= 1:
                    interval = min(RATE_LIMIT_MAX_BACKOFF_SECONDS, max(seconds_until_reset, RATE_LIMIT_FLOOR_SECONDS))
                else:
                    interval = seconds_until_reset / remaining
                    interval = max(RATE_LIMIT_FLOOR_SECONDS, min(interval, RATE_LIMIT_MAX_BACKOFF_SECONDS))
            else:
                interval = settings.request_min_interval_seconds

            bucket.next_allowed = time.monotonic() + interval

            if response.status_code == 429:
                raw = response.headers.get('Retry-After')
                try:
                    retry = float(raw) if raw else float(settings.retry_after_floor_seconds)
                except (TypeError, ValueError):
                    retry = float(settings.retry_after_floor_seconds)
                retry = max(retry, float(settings.retry_after_floor_seconds))
                bucket.blocked_until = time.monotonic() + retry
                raise RateLimitError(retry)
            return response

    async def listings(self, typ, sort_by, limit=50, cursor=None, **filters):
        params = {'limit': min(int(limit), 50), 'sort_by': sort_by, 'type': typ}
        if cursor:
            params['cursor'] = cursor
        params.update({k: v for k, v in filters.items() if v is not None})
        response = await self._request('listings', 'GET', '/listings', params=params)
        if response.status_code >= 400:
            raise CSFloatAPIError(response.status_code, response.text)
        return unwrap(response.json())
    
# Historical sales retrieval.
    async def sales_history(self, name, limit=100, paint_index=None):
        path = '/history/' + quote(name, safe='') + '/sales'
        params = {'limit': min(int(limit), 100)}
        if paint_index is not None:
            params['paint_index'] = int(paint_index)
        response = await self._request('sales_history', 'GET', path, params=params)
        if response.status_code in (401, 403, 404):
            return []
        if response.status_code >= 400:
            raise CSFloatAPIError(response.status_code, response.text)
        return unwrap(response.json())[0]

    async def me(self):
        response = await self._request('me', 'GET', '/me')
        if response.status_code >= 400:
            raise CSFloatAPIError(response.status_code, response.text)
        return response.json()

    async def close(self):
        if not self.client.is_closed:
            await self.client.aclose()
