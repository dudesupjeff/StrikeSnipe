from statistics import median, pstdev, mean
import math, re, time
from .config import settings


def quantile(values, p):
    xs = sorted(float(x) for x in values if x is not None and float(x) > 0)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def robust(values):
    xs = sorted(float(x) for x in values if x is not None and float(x) > 0)
    if len(xs) < 5:
        return xs
    q1, q3 = quantile(xs, .25), quantile(xs, .75)
    iqr = q3 - q1
    clipped = [x for x in xs if q1 - 1.5 * iqr <= x <= q3 + 1.5 * iqr]
    return clipped or xs

def robust_points(points):
    prices = [p for p, _, _ in points if p is not None and p > 0]
    if len(prices) < 5:
        return points
    xs = sorted(prices)
    q1, q3 = quantile(xs, .25), quantile(xs, .75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    trimmed = [(p, t, f) for p, t, f in points if lo <= p <= hi]
    return trimmed or points


def float_percentile(value, samples):
    if value is None or not samples:
        return None
    xs = sorted(float(x) for x in samples if x is not None)
    return 100.0 * sum(x <= float(value) for x in xs) / len(xs) if xs else None

WEAR_TIER_ABBR = {
    'Factory New': 'FN',
    'Minimal Wear': 'MW',
    'Field-Tested': 'FT',
    'Well-Worn': 'WW',
    'Battle-Scarred': 'BS',
}
WEAR_TIER_FLOAT_RANGE = {
    'FN': (0.00, 0.07),
    'MW': (0.07, 0.15),
    'FT': (0.15, 0.38),
    'WW': (0.38, 0.45),
    'BS': (0.45, 1.00),
}
_WEAR_RE = re.compile(r'\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)\s*$')

# 
#
#
# A new section will eventually be here that better evaluates listings with a float on the near max or min of float cap ranges
#
#
#
def wear_tier_from_name(name):
    match = _WEAR_RE.search(str(name or ''))
    if not match:
        return None
    full = match.group(1)
    return WEAR_TIER_ABBR.get(full, full)


def sale_points(rows):
    raw = []
    for row in rows or []:
        if not row:
            continue
        price = row[0]
        float_value = row[1] if len(row) >= 2 else None
        ts = row[4] if len(row) >= 5 else row[-1]
        if price is not None and price > 0 and ts is not None:
            raw.append((float(price), ts, float_value))

    seen_buckets = {}
    for price, ts, fv in raw:
        bucket_key = (price, int(ts // 300))
        if bucket_key not in seen_buckets:
            seen_buckets[bucket_key] = (price, ts, fv)
    return list(seen_buckets.values())

def recency_weighted_median(points, current_float=None, wear_tier=None):
    if not points:
        return None
    now = time.time()
    tier_lo, tier_hi = WEAR_TIER_FLOAT_RANGE.get(wear_tier, (0.0, 1.0))
    tier_width = max(tier_hi - tier_lo, 1e-6)
    bandwidth = tier_width * 0.15 
    use_float_weighting = current_float is not None
    weighted = []
    for price, ts, float_value in points:
        try:
            age_days = max(0.0, (now - float(ts)) / 86400.0) if ts else settings.history_days / 2
        except Exception:
            age_days = settings.history_days / 2
        recency_weight = max(0.05, 0.5 ** (age_days / 7.0))
        if use_float_weighting and float_value is not None:
            delta = abs(float(float_value) - float(current_float)) / bandwidth
            float_weight = max(0.15, math.exp(-(delta ** 2)))
        else:
            float_weight = 1.0
        weighted.append((price, recency_weight * float_weight))
    weighted.sort(key=lambda z: z[0])
    total = sum(w for _, w in weighted)
    acc = 0.0
    for price, w in weighted:
        acc += w
        if acc >= total / 2:
            return price
    return weighted[-1][0]

def kind_from(item):
    name = str(item.get('market_hash_name') or '')
    low = name.lower()
    api_type = str(item.get('type') or '').lower()
    type_name = str(item.get('type_name') or '').lower()
    if low.startswith('sticker |') or low.startswith('sticker capsule') or 'sticker capsule' in low:
        return 'sticker'
    if low.startswith('case |') or low.endswith(' case') or low.startswith('case '):
        return 'case'
    if low.endswith(' key') or low.startswith('key ') or ' key' in low or 'key' in api_type or 'key' in type_name:
        return 'key'
    if (low.startswith('charm |') or 'charm' in api_type or 'charm' in type_name
            or 'keychain' in api_type or 'keychain' in type_name
            or item.get('keychain_index') is not None or item.get('keychains')):
        return 'charm'
    return 'skin'

def pattern_signal(item, same_seed, base):
    notes, factor = [], 1.0
    seed = item.get('paint_seed')
    phase = item.get('phase') or ''
    fade = item.get('fade') or {}
    blue = item.get('blue_gem') or {}
    if seed is not None and len(same_seed) >= 6 and base:
        seed_med = median(same_seed)
        if seed_med > base * 1.06:
            factor = min(1.08, seed_med / base)
            notes.append(f'paint seed {seed} supported by same-seed evidence')
    if phase:
        notes.append(f'Doppler phase: {phase}')
    if isinstance(fade, dict) and fade.get('percentage') is not None:
        notes.append(f'Fade {fade.get("percentage")}% metadata')
    if isinstance(blue, dict) and any(isinstance(v, (int, float)) and v > 0 for v in blue.values()):
        notes.append('Blue-gem metadata present; no premium without sale evidence')
    return factor, notes

def auction_minutes(listing):
    raw = (listing.get('auction_details') or {}).get('expires_at') or listing.get('expires_at')
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw) / 1000.0 if float(raw) > 10_000_000_000 else float(raw)
        else:
            from datetime import datetime
            ts = datetime.fromisoformat(str(raw).replace('Z', '+00:00')).timestamp()
        return (ts - time.time()) / 60.0
    except Exception:
        return None

def evaluate(listing, comps, observed, sales_rows, same_seed, float_samples, liquidity_sales_rows=None):
    item = listing.get('item') or {}
    name = str(item.get('market_hash_name') or '')
    kind = kind_from(item)
    price = listing.get('price')
    if not name or price is None:
        return None
    if item.get('is_souvenir') is True or name.startswith('Souvenir '):
        return None
    price = int(price)

    if liquidity_sales_rows is None:
        liquidity_sales_rows = sales_rows

    sale_pts = sale_points(sales_rows)
    sale_prices = robust([p for p, _, _ in sale_pts])

    liquidity_pts = sale_points(liquidity_sales_rows)
    liquidity_prices = robust([p for p, _, _ in liquidity_pts])
    recent_sales_count = len(liquidity_prices)
    liquidity_required = settings.min_recent_sales
    liquidity_ok = recent_sales_count >= liquidity_required

    current = robust(comps)
    obs = robust(observed or [])

    current_float = item.get('float_value')
    tier = wear_tier_from_name(name)
    sales_med = recency_weighted_median(robust_points(sale_pts), current_float=current_float, wear_tier=tier)
    comp_q25 = quantile(current, .25)
    obs_med = median(obs) if obs else None
    estimates, evidence = [], []
    if sales_med is not None:
        # Exact sales are not always available for every item.
        estimates.append(sales_med)
        evidence.append('recent exact-item sales')
    if comp_q25 is not None:
        estimates.append(comp_q25); evidence.append('current exact-item listings')
    elif current:
        estimates.append(min(current)); evidence.append('current exact-item listing')
    if obs_med is not None:
        estimates.append(obs_med); evidence.append('local exact-item observations')
    if not estimates:
        return None

    fair = min(estimates)
    factor, notes = pattern_signal(item, same_seed, fair)
    fair *= factor
    fp = float_percentile(item.get('float_value'), float_samples)
    if fp is not None:
        notes.append(f'float percentile {fp:.1f}% of local samples <= this float (same exact wear tier)')
    if kind == 'skin' and fp is not None and len(float_samples) >= 75 and fp <= 1.0:
        fair *= 1.005
        notes.append('0.5% extreme-float safety adjustment')

    scm = item.get('scm') or {}
    scm_price = scm.get('price')
    scm_volume = scm.get('volume')
    steam_capped = False
    try:
        scm_price = int(scm_price) if scm_price else None
    except (TypeError, ValueError):
        scm_price = None
    have_solid_sales_evidence = recent_sales_count >= 3
    if (scm_price and scm_price > 0 and factor <= 1.0001
            and not have_solid_sales_evidence and fair > scm_price * 1.20):
        fair = float(scm_price)
        steam_capped = True
        notes.append('capped to live Steam Market price (thin/no direct sales evidence to support pricing this far above it)')

    exit_safety = min(settings.exit_safety_usd * 100.0, fair * 0.15)
    fair = max(1.0, fair - exit_safety)
    net = fair * (1.0 - settings.seller_fee_rate)
    effective_buy = price
    if listing.get('type') == 'auction':
        try:
            min_next_bid = int((listing.get('auction_details') or {}).get('min_next_bid') or price)
            effective_buy = max(min_next_bid, price)
        except Exception:
            effective_buy = price
    profit = net - effective_buy
    roi = profit / effective_buy * 100.0 if effective_buy > 0 else -999.0
    discount = (fair - effective_buy) / fair * 100.0 if fair > 0 else 0.0
    max_buy = min(
        settings.max_buy_price_usd * 100.0,
        net - settings.min_profit_usd * 100.0,
        net / (1.0 + settings.min_roi_percent / 100.0),
    )

    confidence = ( # adjust min confidence in configs/dashboard or .env not here
        15
        + min(40, recent_sales_count * 8)
        + min(15, max(0, len(sale_prices) - recent_sales_count) * 3)
        + min(20, len(current) * 3)
        + min(10, len(obs) // 25)
    )
    if kind in ('sticker', 'case', 'charm'):
        confidence += 5 # means it is a bit more stable and likely to stay at a similar price so it gets a reward of +5
    if recent_sales_count >= settings.min_recent_sales_for_strong_confidence:
        confidence += 5 # just means it is a higher chance of being a good selling item so it gets a reward of +5

    try:
        if scm_volume is not None and int(scm_volume) >= 20:
            confidence += 3
    except (TypeError, ValueError):
        pass

    dedup_prices = [p for p, _, _ in sale_pts]
    if len(dedup_prices) >= 3:
        try:
            avg_price = mean(dedup_prices)
            cv = (pstdev(dedup_prices) / avg_price) if avg_price > 0 else 0.0
            if cv > 0.35:
                penalty = min(35, int((cv - 0.35) * 60))
                confidence -= penalty
                notes.append(f'high sale-price dispersion (cv={cv:.2f}) - confidence reduced {penalty} pts')
        except (ZeroDivisionError, ValueError):
            pass

    confidence = min(98, max(5, int(confidence)))
    if not liquidity_ok:
        reason = f'not alertable: {recent_sales_count} sales in last {settings.sales_lookback_days}d; need {liquidity_required}'
    elif effective_buy > settings.max_buy_price_usd * 100:
        reason = 'above max buy price'
    elif listing.get('type') == 'auction':
        mins = auction_minutes(listing)
        if mins is not None and not (settings.auction_min_minutes <= mins <= settings.auction_max_minutes): # gives brief reasoning for why it isn't good, ideally this section will be expanded and revamped...a later day
            reason = 'auction outside time window'
        elif profit < settings.min_profit_usd * 100:
            reason = 'profit below threshold'
        elif roi < settings.min_roi_percent:
            reason = 'ROI below threshold'
        elif discount < settings.min_discount_percent:
            reason = 'discount below threshold'
        elif confidence < settings.min_confidence:
            reason = 'confidence below threshold'
        else:
            reason = 'qualifies'
    elif profit < settings.min_profit_usd * 100:
        reason = 'profit below threshold'
    elif roi < settings.min_roi_percent:
        reason = 'ROI below threshold'
    elif discount < settings.min_discount_percent:
        reason = 'discount below threshold'
    elif confidence < settings.min_confidence:
        reason = 'confidence below threshold'
    else:
        reason = 'qualifies'

    return {
        'name': name, 'kind': kind, 'wear_tier': wear_tier_from_name(name), 'price_cents': price,
        'effective_buy_cents': round(effective_buy),
        'fair_cents': round(fair), 'net_cents': round(net), 'profit_cents': round(profit),
        'roi': round(roi, 2), 'discount': round(discount, 2), 'max_buy_cents': max(0, round(max_buy)),
        'confidence': confidence, 'comparables': len(current), 'sales_points': len(sale_prices),
        'recent_sales_points': recent_sales_count,
        'liquidity_ok': liquidity_ok, 'recent_sales_required': liquidity_required,
        'history_points': len(observed or []), 'float_value': item.get('float_value'), 'paint_seed': item.get('paint_seed'),
        'paint_index': item.get('paint_index'), 'wear_name': item.get('wear_name'),
        'keychain_pattern': item.get('keychain_pattern'), 'pattern_notes': notes,
        'scm_price_cents': scm_price, 'scm_volume': scm_volume, 'steam_capped': steam_capped,
        'evidence_type': evidence, 'listing_type': listing.get('type', 'buy_now'), 'reason': reason,
    }

def is_opportunity(v):
    return bool(v and v.get('reason') == 'qualifies' and v.get('evidence_type'))