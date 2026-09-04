import httpx
from .config import settings

def money(c):
    return f'${c/100:,.2f}'

# Here is your code for sending Discord notifications, you can edit a decent bit of this to fit what you need and or want to have displayed in the discord message. 
# What is currently present is what would generally be needed to be displayed for a user to make a decision on whether they would like to pursue a listing or not.
# optionally you could add more fields to the embed such as displaying diagnostic information like listings, sales, and observed listings.
# Additions to the noti that display the above ideas could be useful if you plan on running it "headless" or really just not checking screen and doing it from your phone... 
async def send_discord(listing, v):
    if not settings.discord_webhook_url:
        raise RuntimeError('DISCORD_WEBHOOK_URL is missing in .env') # if your discord url is missing or no worky
    lid = str(listing.get('id')) 
    url = f'https://csfloat.com/item/{lid}' # Link to the CSFloat item page
    kind = 'AUCTION' if listing.get('type') == 'auction' else 'LOW BIN' # type of listing
    item = listing.get('item') or {} # item details of the listing
    wear = v.get('wear_tier') #wear tier of the item, if applicable (aka not a sticker, case, or key)
    signals = '\n'.join('• ' + s for s in v.get('pattern_notes', [])[:8]) or '• No premium adjustment applied' 
    steam_line = ''
    if v.get('scm_price_cents'):
        steam_line = f'Steam Market ref: {money(v["scm_price_cents"])} (volume {v.get("scm_volume", "n/a")})\n'
    desc = (
        f'Buy: {money(v["price_cents"])}\n'  # example template for if you were to modify and or add more fields -> f'Example field: {v.get("example_field", "n/a")}\n'
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
        'title': f'🔥 CSFloat {kind}{" · " + wear if wear else ""}: {v["name"]}', 'url': url, 'description': desc, #this will appear at the very top (shocker the title is at the)
        'fields': [ # specific skin type stats like float, seed, and whatnot
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

async def send_test(): #this is where the "test discord" button on the dashboard calls to for sending the test message.
    if not settings.discord_webhook_url:
        raise RuntimeError('DISCORD_WEBHOOK_URL is missing in .env')
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(settings.discord_webhook_url, json={'content': 'StrikeSnipe connected successfully!'}) # you can modify this message within the '' to whatever you want it to say...and add embeds if you want but not much of a point
        response.raise_for_status()
