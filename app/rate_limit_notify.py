import time
import httpx
from .config import settings


_COOLDOWN_SECONDS = 600 #important so you dont get spammed (yes it happened to me)
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
    resume_at = time.strftime('%H:%M:%S', time.localtime(now + retry_after)) # if it recieves any rate limits it will send a discord message... if you keep the default scan speeds and even a little faster than default it will likely never hit a rate limit
    content = (
        f'**StrikeSnipe rate limited**{where}\n'
        f'Cooling down for {int(retry_after)}s — next attempt around {resume_at} local time.\n'
        f'(Further rate-limit notices are suppressed for {_COOLDOWN_SECONDS // 60} minutes ' #once again just points out that it will just limit the spam...you are aware it happened and thats all that matters...you can always check the logs for more details if you want to see what happened
        f'to avoid spamming this channel.)'
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.discord_webhook_url, json={'content': content})
            response.raise_for_status()
        return True
    except Exception:

        return False
