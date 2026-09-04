import httpx
from .config import settings

def money(c):
    return f'${c/100:,.2f}'

async def send_discord(listing, v):
    if not settings.discord_webhook_url:
        raise RuntimeError('DISCORD_WEBHOOK_URL is missing in .env')
    lid = str(listing.get('id'))
    url = f'https://csfloat.com/item/{lid}'
    kind = 'AUCTION' if listing.get('type') == 'auction' else 'LOW BIN'
    item = listing.get('item') or {}
    wear = v.get('wear_tier')
    signals = '\n'.join('• ' + s for s in v.get('pattern_notes', [])[:8]) or '• No premium adjustment applied'
    steam_line = ''
    if v.get('scm_price_cents'):
        steam_line = f'Steam Market ref: {money(v["scm_price_cents"])} (volume {v.get("scm_volume", "n/a")})\n'
    desc = (
        f'Buy: {money(v["price_cents"])}\n'
        f'Safe resale: {money(v["fair_cents"])}\n'
        f'Expected net: {money(v["net_cents"])}\n'
        f'Profit: +{money(v["profit_cents"])}\n'
        f'ROI: {v["roi"]}%\n'
        f'Max buy: {money(v["max_buy_cents"])}\n'
        f'Discount: {v["discount"]}%\n'
        f'Confidence: {v["confidence"]}/100\n'
        f'Sales (last {settings.sales_lookback_days}d): {v.get("recent_sales_points", v.get("sales_points", 0))}\n'
        f'{steam_line}\n'
        f'Evidence: {", ".join(v.get("evidence_type", []))}\n{signals}\n\n'
        f'[Open CSFloat manually]({url})'
    )
    embed = {
        'title': f'🔥 CSFloat {kind}{" · " + wear if wear else ""}: {v["name"]}', 'url': url, 'description': desc,
        'fields': [
            {'name': 'Comparables', 'value': str(v['comparables']), 'inline': True},
            {'name': 'Historical sales', 'value': str(v['sales_points']), 'inline': True},
            {'name': 'Observed', 'value': str(v['history_points']), 'inline': True},
            {'name': 'Float', 'value': str(item.get('float_value')) if item.get('float_value') is not None else 'n/a', 'inline': True},
            {'name': 'Paint seed', 'value': str(item.get('paint_seed')) if item.get('paint_seed') is not None else 'n/a', 'inline': True},
        ],
        'footer': {'text': 'Always double check the item manually before buying as errors may occur, listings may have been removed, changed, or not worth purchasing'}
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(settings.discord_webhook_url, json={'embeds': [embed]})
        response.raise_for_status()
    return True

async def send_test():
    if not settings.discord_webhook_url:
        raise RuntimeError('DISCORD_WEBHOOK_URL is missing in .env')
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(settings.discord_webhook_url, json={'content': 'StrikeSnipe connected successfully!'})
        response.raise_for_status()
