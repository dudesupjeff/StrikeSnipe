import json
import time
import re
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from .config import settings
from .db import (
    connect, recent_alerts, counts, blacklisted_skins, blacklist_skin, remove_blacklist,
    clear_listings_and_observations, clear_sales, clear_alerts, clear_all,
)
from .scanner import Scanner
from .csfloat import CSFloatClient, RateLimitError
from .notify import send_test

scanner = Scanner()

@asynccontextmanager
async def lifespan(app):
    yield
    if scanner.running:
        await scanner.stop()

app = FastAPI(title='StrikeSnipe', version='3.1', lifespan=lifespan)

@app.get('/', response_class=HTMLResponse)
async def root():
    return (Path(__file__).parent / 'dashboard.html').read_text(encoding='utf-8')

@app.get('/api/status')
async def status():
    db = await connect()
    try:
        c = await counts(db)
        rows = await recent_alerts(db, 50)
        return {
            'running': scanner.running,
            'phase': scanner.phase,
            'connected': scanner.connected,
            'last_error': scanner.last_error,
            'last_scan': scanner.last_scan,
            'last_cycle_started': scanner.last_cycle_started,
            'last_cycle_finished': scanner.last_cycle_finished,
            'rate_limited_until': scanner.rate_limited_until,
            'requests_this_cycle': scanner.requests_this_cycle,
            'total_requests': scanner.client.request_count if scanner.client else scanner.total_requests,
            'rate_limit_snapshot': scanner.client.rate_limit_snapshot if scanner.client else {},
            'stats': scanner.stats,
            'reasons': dict(scanner.last_reasons),
            'recent_candidates': scanner.recent_candidates,
            'settings': {
                'max_buy_price_usd': settings.max_buy_price_usd,
                'min_buy_price_usd': settings.min_buy_price_usd,
                'min_profit_usd': settings.min_profit_usd,
                'min_roi_percent': settings.min_roi_percent,
                'min_discount_percent': settings.min_discount_percent,
                'min_confidence': settings.min_confidence,
                'seller_fee_rate': settings.seller_fee_rate,
                'poll_seconds': settings.poll_seconds,
                'request_delay': settings.request_min_interval_seconds,
                'exclude_souvenirs': settings.exclude_souvenirs,
                'exclude_stickered': settings.exclude_stickered,
                'include_skins': settings.include_skins,
                'include_stickers': settings.include_stickers,
                'include_cases': settings.include_cases,
                'include_charms': settings.include_charms,
                'include_keys': settings.include_keys,
                'min_recent_sales': settings.min_recent_sales,
                'sales_lookback_days': settings.sales_lookback_days,
                'comparables_lookback_days': settings.comparables_lookback_days,
                'max_historical_fetches_per_cycle': settings.max_historical_fetches_per_cycle,
                'max_comparable_lookups_per_cycle': settings.max_comparable_lookups_per_cycle,
                'auction_pages_per_cycle': settings.auction_pages_per_cycle,
                'sales_cache_hours': settings.sales_cache_hours,
                'request_min_interval_seconds': settings.request_min_interval_seconds,
                'max_candidates_per_cycle': settings.max_candidates_per_cycle,
                'max_alerts_per_hour': settings.max_alerts_per_hour,
                'discord_configured': bool(settings.discord_webhook_url),
                'auctions_only': settings.auctions_only,
                'enable_auctions': settings.enable_auctions,
                'auction_min_minutes': settings.auction_min_minutes,
                'auction_max_minutes': settings.auction_max_minutes,
            },
            **c,
            'alerts_recent': [
                {'listing_id': r[0], 'sent_at': r[1], 'profit_cents': r[2], 'roi': r[3], 'fair_cents': r[4], 'reason': r[5], 'payload': json.loads(r[6] or '{}'), 'url': f'https://csfloat.com/item/{r[0]}'}
                for r in rows
            ],
            'blacklisted_skins': [r[0] for r in await blacklisted_skins(db)],
        }
    finally:
        await db.close()

@app.post('/api/scanner/start')
async def start():
    started = await scanner.start()
    return {'ok': True, 'started': started, 'running': scanner.running}

@app.post('/api/scanner/stop')
async def stop():
    stopped = await scanner.stop()
    return {'ok': True, 'stopped': stopped, 'running': scanner.running}

@app.post('/api/scanner/scan-once')
async def scan_once():
    ok, message = await scanner.scan_once()
    return {'ok': ok, 'message': message}

@app.post('/api/data/clear-listings')
async def clear_listings_endpoint():
    if scanner.running:
        return {'ok': False, 'error': 'Stop the scanner before clearing listings.'}
    db = await connect()
    try:
        await clear_listings_and_observations(db)
        return {'ok': True, 'message': 'Listings and observations cleared.'}
    finally:
        await db.close()

@app.post('/api/data/clear-sales')
async def clear_sales_endpoint():
    if scanner.running:
        return {'ok': False, 'error': 'Stop the scanner before clearing sales history.'}
    db = await connect()
    try:
        await clear_sales(db)
        return {'ok': True, 'message': 'Sales history and sales cache cleared.'}
    finally:
        await db.close()

@app.post('/api/data/clear-alerts')
async def clear_alerts_endpoint():
    if scanner.running:
        return {'ok': False, 'error': 'Stop the scanner before clearing alert history.'}
    db = await connect()
    try:
        await clear_alerts(db)
        return {'ok': True, 'message': 'Alert history cleared (previously alerted listings can re-alert).'}
    finally:
        await db.close()

@app.post('/api/data/clear-all')
async def clear_all_endpoint():
    if scanner.running:
        return {'ok': False, 'error': 'Stop the scanner before doing a full reset.'}
    db = await connect()
    try:
        await clear_all(db, keep_blacklist=True)
        return {'ok': True, 'message': 'Full database reset (listings, observations, sales, sales cache, alerts). Blacklist kept.'}
    finally:
        await db.close()

@app.post('/api/test/csfloat')
async def test_csfloat():
    if not settings.csfloat_api_key:
        return {'ok': False, 'error': 'CSFLOAT_API_KEY is missing in .env'}
    client = CSFloatClient()
    try:
        me = await client.me()
        return {'ok': True, 'message': 'CSFloat authentication succeeded', 'user': me.get('username') or me.get('user', {}).get('username') or 'authenticated'}
    except RateLimitError as exc:
        return {'ok': False, 'error': f'CSFloat rate limited; retry after {int(exc.retry_after)}s'}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
    finally:
        await client.close()

@app.post('/api/test/discord')
async def test_discord():
    try:
        await send_test()
        return {'ok': True, 'message': 'Discord webhook accepted the test alert'}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

@app.get('/api/blacklist')
async def get_blacklist():
    db = await connect()
    try:
        return {'ok': True, 'skins': [{'name': row[0], 'created_at': row[1]} for row in await blacklisted_skins(db)]}
    finally:
        await db.close()

@app.post('/api/blacklist')
async def add_blacklist(payload: dict):
    name = str(payload.get('market_hash_name') or '').strip()
    if not name or len(name) > 200:
        return {'ok': False, 'error': 'Enter a valid market hash name.'}
    db = await connect()
    try:
        await blacklist_skin(db, name)
        return {'ok': True, 'name': name}
    finally:
        await db.close()

@app.delete('/api/blacklist')
async def delete_blacklist(payload: dict):
    name = str(payload.get('market_hash_name') or '').strip()
    if not name:
        return {'ok': False, 'error': 'Missing market hash name.'}
    db = await connect()
    try:
        await remove_blacklist(db, name)
        return {'ok': True}
    finally:
        await db.close()



_NUMERIC_SETTINGS = {
    'max_buy_price_usd': (float, 0.01, None),
    'min_buy_price_usd': (float, 0.0, None),
    'min_profit_usd': (float, 0.01, None),
    'min_roi_percent': (float, 0.0, None),
    'min_discount_percent': (float, 0.0, None),
    'min_confidence': (int, 0, 100),
    'auction_max_minutes': (int, 1, None),
    'auction_min_minutes': (int, 0, None),
    'auction_pages_per_cycle': (int, 1, 4),
    'min_recent_sales': (int, 0, None),
    'sales_lookback_days': (int, 1, None),
    'comparables_lookback_days': (int, 1, 30),
    'max_historical_fetches_per_cycle': (int, 0, 20),
    'max_comparable_lookups_per_cycle': (int, 0, 20),
    'poll_seconds': (int, 30, None),
    'sales_cache_hours': (float, 1.0, 168.0),
    'request_min_interval_seconds': (float, 3.0, 60.0),
    'max_candidates_per_cycle': (int, 5, 100),
    'max_alerts_per_hour': (int, 1, 200),
}
_BOOL_SETTINGS = {
    'auctions_only', 'enable_auctions', 'exclude_souvenirs', 'exclude_stickered',
    'include_skins', 'include_stickers', 'include_cases', 'include_charms', 'include_keys',
}
_ALLOWED_SETTINGS = set(_NUMERIC_SETTINGS) | _BOOL_SETTINGS


@app.post('/api/settings')
async def update_settings(payload: dict):
    changed = {}
    for key in _ALLOWED_SETTINGS:
        if key not in payload:
            continue
        raw = payload[key]
        try:
            if key in _BOOL_SETTINGS:
                value = bool(raw)
            else:
                caster, lo, hi = _NUMERIC_SETTINGS[key]
                value = caster(raw)
                if lo is not None:
                    value = max(lo, value)
                if hi is not None:
                    value = min(hi, value)
            setattr(settings, key, value)
            env_key = key.upper()
            try:
                text = open('.env', encoding='utf-8').read()
                env_value = str(value).lower() if isinstance(value, bool) else value
                text, count = re.subn(rf'(?m)^{env_key}=.*$', f'{env_key}={env_value}', text)
                if count:
                    open('.env', 'w', encoding='utf-8').write(text)
                else:
                    with open('.env', 'a', encoding='utf-8') as fh:
                        fh.write(f'\n{env_key}={env_value}\n')
            except OSError:
                pass
            changed[key] = value
        except (TypeError, ValueError):
            return {'ok': False, 'error': f'Invalid value for {key}'}

    # Keep the response shape aligned with the dashboard configuration fields.
    settings.max_buy_price_usd = max(0.01, float(settings.max_buy_price_usd))
    settings.min_buy_price_usd = max(0.0, min(float(settings.min_buy_price_usd), settings.max_buy_price_usd))
    settings.min_profit_usd = max(0.01, float(settings.min_profit_usd))
    settings.min_roi_percent = max(0.0, float(settings.min_roi_percent))
    settings.min_discount_percent = max(0.0, float(settings.min_discount_percent))
    settings.min_confidence = min(100, max(0, int(settings.min_confidence)))
    settings.min_recent_sales = max(0, int(settings.min_recent_sales))
    settings.sales_lookback_days = max(1, int(settings.sales_lookback_days))
    settings.comparables_lookback_days = max(1, int(settings.comparables_lookback_days))
    settings.auction_min_minutes = max(0, int(settings.auction_min_minutes))
    settings.auction_max_minutes = max(settings.auction_min_minutes + 1, int(settings.auction_max_minutes))
    settings.min_scan_price_cents = max(0, int(round(settings.min_buy_price_usd * 100)))
    settings.max_scan_price_cents = max(settings.min_scan_price_cents + 1, int(round(settings.max_buy_price_usd * 100)) + 1)
    return {'ok': True, 'settings': changed}
