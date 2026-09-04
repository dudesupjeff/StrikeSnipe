import time
import httpx
from .config import settings


_COOLDOWN_SECONDS = 600
_last_notified_at = 0.0


async def notify_rate_limited(retry_after, context=''):
    global _last_notified_at
    now = time.time()
    if now - _last_notified_at < _COOLDOWN_SECONDS:
        return False
    if not settings.discord_webhook_url:
        return False

    _last_notified_at = now
    where = f' ({context})' if context else ''
    resume_at = time.strftime('%H:%M:%S', time.localtime(now + retry_after))
    content = (
        f'**StrikeSnipe rate limited**{where}\n'
        f'Cooling down for {int(retry_after)}s — next attempt around {resume_at} local time.\n'
        f'(Further rate-limit notices are suppressed for {_COOLDOWN_SECONDS // 60} minutes '
        f'to avoid spamming this channel.)'
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.discord_webhook_url, json={'content': content})
            response.raise_for_status()
        return True
    except Exception:

        return False
