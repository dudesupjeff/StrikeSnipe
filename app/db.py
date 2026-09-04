import aiosqlite
import hashlib
import json
import os
import time
from datetime import datetime
from .config import settings

# Database schema...no touchy cause it creates the tables if they dont exist yet (aka first run/new db) and set up indexes... if you touch it breaks
SCHEMA = '''
CREATE TABLE IF NOT EXISTS listings(
 id TEXT PRIMARY KEY, market_hash_name TEXT, listing_type TEXT, state TEXT,
 price_cents INTEGER, float_value REAL, paint_seed INTEGER, paint_index INTEGER,
 wear_name TEXT, is_stattrak INTEGER, is_souvenir INTEGER, created_at TEXT,
 first_seen REAL, last_seen REAL, raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_name_time ON listings(market_hash_name,last_seen);
CREATE INDEX IF NOT EXISTS idx_listings_name_price ON listings(market_hash_name,price_cents,last_seen);
CREATE INDEX IF NOT EXISTS idx_listings_name_seed ON listings(market_hash_name,paint_seed,last_seen);
CREATE TABLE IF NOT EXISTS observations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id TEXT, market_hash_name TEXT,
 listing_type TEXT, price_cents INTEGER, observed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_obs_name_time ON observations(market_hash_name,observed_at);
CREATE TABLE IF NOT EXISTS sales(
 sale_key TEXT PRIMARY KEY, market_hash_name TEXT, price_cents INTEGER, sold_ts REAL,
 float_value REAL, paint_seed INTEGER, paint_index INTEGER, raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sales_name_time ON sales(market_hash_name,sold_ts);
CREATE TABLE IF NOT EXISTS sales_cache(market_hash_name TEXT PRIMARY KEY, fetched_at REAL, points INTEGER);
CREATE INDEX IF NOT EXISTS idx_sales_cache_fetched ON sales_cache(fetched_at);
CREATE TABLE IF NOT EXISTS alerts(
 listing_id TEXT PRIMARY KEY, sent_at REAL, profit_cents INTEGER, roi REAL,
 fair_cents INTEGER, reason TEXT, payload_json TEXT
);
CREATE TABLE IF NOT EXISTS blacklisted_skins(
 market_hash_name TEXT PRIMARY KEY, created_at REAL
);
'''
async def connect():
    os.makedirs(os.path.dirname(settings.database_path) or '.', exist_ok=True)
    db = await aiosqlite.connect(settings.database_path)
    await db.executescript(SCHEMA)
    await db.commit()
    return db

def is_souvenir(item, name):
    return bool(item.get('is_souvenir') is True or str(name or '').startswith('Souvenir '))

def is_stickered(item):
    return bool(item.get('stickers'))
#the process the responses go through when saved into the db and how it inserts the data. Ideally don't change anything
async def upsert_listings(db, items):
    now = time.time()
    stored = 0
    for listing in items or []:
        item = listing.get('item') or {}
        name = item.get('market_hash_name')
        if not name:
            continue
        if settings.exclude_souvenirs and is_souvenir(item, name):
            continue
        if settings.exclude_stickered and is_stickered(item):
            continue
        lid = str(listing.get('id') or '')
        if not lid:
            continue
        try:
            price = int(listing.get('price'))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if price < settings.min_scan_price_cents or price > settings.max_scan_price_cents:
            continue
        await db.execute('''
            INSERT INTO listings(id,market_hash_name,listing_type,state,price_cents,float_value,paint_seed,paint_index,wear_name,is_stattrak,is_souvenir,created_at,first_seen,last_seen,raw_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              market_hash_name=excluded.market_hash_name, listing_type=excluded.listing_type,
              state=excluded.state, price_cents=excluded.price_cents, float_value=excluded.float_value,
              paint_seed=excluded.paint_seed, paint_index=excluded.paint_index, wear_name=excluded.wear_name,
              last_seen=excluded.last_seen, raw_json=excluded.raw_json
        ''', (
            lid, name, listing.get('type'), listing.get('state'), price,
            item.get('float_value'), item.get('paint_seed'), item.get('paint_index'), item.get('wear_name'),
            1 if item.get('is_stattrak') else 0, 1 if item.get('is_souvenir') else 0,
            listing.get('created_at'), now, now, json.dumps(listing, separators=(',', ':'))
        ))
        await db.execute('INSERT INTO observations(listing_id,market_hash_name,listing_type,price_cents,observed_at) VALUES(?,?,?,?,?)', (lid, name, listing.get('type'), price, now))
        stored += 1
    await db.commit()
    return stored
# most of the async functions are used to query the db for specific data and return or place it...this is a weird mix of my code and claude telling me im stupid and its better a certain way  
async def active_comparables(db, name, exclude_id=None, days=3, limit=100):
    cutoff = time.time() - days * 86400
    cur = await db.execute('''SELECT price_cents FROM listings
      WHERE market_hash_name=? AND id<>? AND price_cents IS NOT NULL AND last_seen>=?
      AND (state IS NULL OR state='listed') ORDER BY price_cents ASC LIMIT ?''',
      (name, str(exclude_id or ''), cutoff, limit))
    return [row[0] for row in await cur.fetchall()]

async def active_comparables_escalating(db, name, exclude_id=None, base_days=7, min_count=3, limit=100):
    for days in (base_days, max(base_days * 3, 14), 30):
        rows = await active_comparables(db, name, exclude_id, days=days, limit=limit)
        if len(rows) >= min_count or days >= 30:
            return rows
    return rows

async def observations(db, name, days=30, limit=2000):
    cutoff = time.time() - days * 86400
    cur = await db.execute('SELECT price_cents FROM observations WHERE market_hash_name=? AND observed_at>=? ORDER BY observed_at DESC LIMIT ?', (name, cutoff, limit))
    return [row[0] for row in await cur.fetchall() if row[0] is not None]

async def same_seed_prices(db, name, seed, days=30, limit=100):
    if seed is None:
        return []
    cutoff = time.time() - days * 86400
    cur = await db.execute('SELECT price_cents FROM listings WHERE market_hash_name=? AND paint_seed=? AND price_cents IS NOT NULL AND last_seen>=? ORDER BY price_cents ASC LIMIT ?', (name, int(seed), cutoff, limit))
    return [row[0] for row in await cur.fetchall()]

async def float_samples(db, name, days=30, limit=5000):
    cutoff = time.time() - days * 86400
    cur = await db.execute('SELECT float_value FROM listings WHERE market_hash_name=? AND float_value IS NOT NULL AND last_seen>=? LIMIT ?', (name, cutoff, limit))
    return [row[0] for row in await cur.fetchall()]

def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000 if value > 10_000_000_000 else value
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    except Exception:
        try:
            return float(text)
        except Exception:
            return None

def extract_sale_price(sale):
    item = sale.get('item') or {}
    for key in ('price_cents', 'price', 'sale_price', 'amount'):
        value = sale.get(key)
        if value is None:
            value = item.get(key)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return None

def extract_sale_timestamp(sale):
    for key in ('sold_at', 'soldAt', 'created_at', 'timestamp', 'date', 'time'):
        if sale.get(key) is not None:
            return parse_ts(sale.get(key))
    return None

async def save_sales(db, name, sales_rows):
    count = 0
    for sale in sales_rows or []:
        item = sale.get('item') or {}
        price = extract_sale_price(sale)
        if price is None or price <= 0:
            continue
        sold_ts = extract_sale_timestamp(sale)
        key = str(sale.get('id') or sale.get('sale_id') or hashlib.sha1(f'{name}|{sold_ts}|{price}|{sale.get("asset_id","")}'.encode()).hexdigest())
        await db.execute('''INSERT OR IGNORE INTO sales(sale_key,market_hash_name,price_cents,sold_ts,float_value,paint_seed,paint_index,raw_json)
            VALUES(?,?,?,?,?,?,?,?)''', (
            key, name, price, sold_ts,
            sale.get('float_value', item.get('float_value')),
            sale.get('paint_seed', item.get('paint_seed')),
            sale.get('paint_index', item.get('paint_index')),
            json.dumps(sale, separators=(',', ':'))
        ))
        count += 1
    await db.commit()
    return count

async def sales_fresh(db, name, hours):
    cur = await db.execute('SELECT fetched_at FROM sales_cache WHERE market_hash_name=?', (name,))
    row = await cur.fetchone()
    return bool(row and time.time() - row[0] < hours * 3600)

async def mark_sales_fetch(db, name, points):
    await db.execute('''INSERT INTO sales_cache(market_hash_name,fetched_at,points) VALUES(?,?,?)
        ON CONFLICT(market_hash_name) DO UPDATE SET fetched_at=excluded.fetched_at,points=excluded.points''', (name, time.time(), int(points)))
    await db.commit()

async def fetch_priority_rank(db, names):
    if not names:
        return []
    names = list(dict.fromkeys(names))
    placeholders = ','.join('?' for _ in names)
    cur = await db.execute(f'SELECT market_hash_name, fetched_at FROM sales_cache WHERE market_hash_name IN ({placeholders})', names)
    fetched = {row[0]: row[1] for row in await cur.fetchall()}
    return sorted(names, key=lambda n: fetched.get(n, 0.0))

async def historical_sales(db, name, days=30, limit=500):
    cutoff = time.time() - days * 86400
    cur = await db.execute('''SELECT price_cents,float_value,paint_seed,paint_index,sold_ts
        FROM sales WHERE market_hash_name=? AND sold_ts IS NOT NULL AND sold_ts>=?
        ORDER BY COALESCE(sold_ts,0) DESC LIMIT ?''', (name, cutoff, limit))
    return await cur.fetchall()

async def alert_sent(db, listing_id):
    cur = await db.execute('SELECT 1 FROM alerts WHERE listing_id=?', (str(listing_id),))
    return await cur.fetchone() is not None

async def is_blacklisted(db, market_hash_name):
    cur = await db.execute('''SELECT 1 FROM blacklisted_skins
        WHERE lower(?)=lower(market_hash_name)
           OR lower(?) LIKE '%' || lower(market_hash_name) || '%' LIMIT 1''',
        (str(market_hash_name or ''), str(market_hash_name or '')))
    return await cur.fetchone() is not None

async def blacklist_skin(db, market_hash_name):
    name = str(market_hash_name or '').strip()
    if not name:
        return False
    await db.execute('INSERT OR IGNORE INTO blacklisted_skins(market_hash_name,created_at) VALUES(?,?)', (name, time.time()))
    await db.commit()
    return True

async def remove_blacklist(db, market_hash_name):
    await db.execute('DELETE FROM blacklisted_skins WHERE market_hash_name=?', (str(market_hash_name),))
    await db.commit()

async def blacklisted_skins(db):
    cur = await db.execute('SELECT market_hash_name,created_at FROM blacklisted_skins ORDER BY market_hash_name')
    return await cur.fetchall()

async def recent_alert_count(db, hours=1):
    cur = await db.execute('SELECT COUNT(*) FROM alerts WHERE sent_at>=?', (time.time() - hours * 3600,))
    return int((await cur.fetchone())[0])

async def save_alert(db, listing_id, valuation, reason):
    await db.execute('''INSERT OR REPLACE INTO alerts(listing_id,sent_at,profit_cents,roi,fair_cents,reason,payload_json)
        VALUES(?,?,?,?,?,?,?)''', (str(listing_id), time.time(), valuation['profit_cents'], valuation['roi'], valuation['fair_cents'], reason, json.dumps(valuation, separators=(',', ':'))))
    await db.commit()

async def recent_alerts(db, limit=50):
    cur = await db.execute('SELECT listing_id,sent_at,profit_cents,roi,fair_cents,reason,payload_json FROM alerts ORDER BY sent_at DESC LIMIT ?', (limit,))
    return await cur.fetchall()

async def counts(db):
    out = {}
    for key, sql in [
        ('listings', 'SELECT COUNT(*) FROM listings'),
        ('sales', 'SELECT COUNT(*) FROM sales'),
        ('alerts', 'SELECT COUNT(*) FROM alerts'),
        ('observations', 'SELECT COUNT(*) FROM observations')
    ]:
        cur = await db.execute(sql)
        out[key] = int((await cur.fetchone())[0])
    return out

async def clear_listings_and_observations(db):
    await db.execute('DELETE FROM listings')
    await db.execute('DELETE FROM observations')
    await db.commit()

async def clear_sales(db):
    await db.execute('DELETE FROM sales')
    await db.execute('DELETE FROM sales_cache')
    await db.commit()

async def clear_alerts(db):
    await db.execute('DELETE FROM alerts')
    await db.commit()

async def clear_all(db, keep_blacklist=True):
    await clear_listings_and_observations(db)
    await clear_sales(db)
    await clear_alerts(db)
    if not keep_blacklist:
        await db.execute('DELETE FROM blacklisted_skins')
        await db.commit()
