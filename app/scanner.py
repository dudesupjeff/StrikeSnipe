import asyncio
import logging
import time
from collections import Counter
from .config import settings
from .csfloat import CSFloatClient, RateLimitError, CSFloatAPIError
from .db import *
from .valuation import evaluate, is_opportunity, kind_from
from .notify import send_discord
from .rate_limit_notify import notify_rate_limited

log = logging.getLogger('strikesnipe')

class Scanner:
    def __init__(self):
        self.running = False
        self.task = None
        self.phase = 'stopped'
        self.connected = False
        self.last_error = ''
        self.last_scan = None
        self.last_cycle_started = None
        self.last_cycle_finished = None
        self.rate_limited_until = None
        self.requests_this_cycle = 0
        self.total_requests = 0
        self.client = None
        self.db_counts = {}
        self._stop = asyncio.Event()
        self.stats = self._fresh_stats()
        self.last_reasons = Counter()
        self.recent_candidates = []

    @staticmethod
    def _fresh_stats():
        return {
            'seen': 0, 'valued': 0, 'opportunities': 0, 'alerts_sent': 0,
            'threshold_rejects': 0, 'history_fetches': 0, 'comparable_lookups': 0,
            'skipped_alerted': 0, 'blacklisted': 0, 'souvenirs_excluded': 0, 'above_max_price': 0,
            'bin_candidates': 0, 'auction_candidates': 0, 'discord_failures': 0,
            'auction_pages_fetched': 0,
        }

    async def start(self):
        if self.running:
            return False
        self.running = True
        self.phase = 'starting'
        self.connected = False
        self.last_error = ''
        self._stop.clear()
        self.task = asyncio.create_task(self._worker(), name='strikesnipe')
        return True

    async def stop(self):
        if not self.running and not self.task:
            return False
        self.running = False
        self._stop.set()
        if self.task:
            try:
                await asyncio.wait_for(self.task, timeout=15)
            except asyncio.TimeoutError:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
        self.task = None
        self.phase = 'stopped'
        return True

    async def scan_once(self):
        if self.running:
            return False, 'Scanner is already running.'
        self.running = True
        self.phase = 'manual-scan'
        self.connected = False
        self.last_error = ''
        self._stop.clear()
        db = None
        client = CSFloatClient()
        self.client = client
        try:
            db = await connect()
            self.requests_this_cycle = 0
            self.stats = self._fresh_stats()
            self.last_reasons = Counter()
            await self._cycle(db, client)
            self.connected = True
            self.last_scan = time.time()
            self.last_cycle_finished = time.time()
            if self.phase != 'rate-limited':
                self.phase = 'idle'
            return True, 'One scan completed.'
        except RateLimitError as exc:
            self.rate_limited_until = time.time() + exc.retry_after
            self.phase = 'rate-limited'
            self.last_error = f'CSFloat rate limited; cooling down {int(exc.retry_after)}s'
            await notify_rate_limited(exc.retry_after, context='manual scan')
            return False, self.last_error
        except Exception as exc:
            self.phase = 'error'
            self.last_error = f'{type(exc).__name__}: {exc}'
            log.exception('manual scan failed')
            return False, self.last_error
        finally:
            try:
                if db:
                    self.db_counts = await counts(db)
            except Exception:
                pass
            if db:
                await db.close()
            await client.close()
            self.client = None
            self.total_requests = client.request_count
            self.running = False

    async def _worker(self):
        db = None
        client = CSFloatClient()
        self.client = client
        try:
            db = await connect()
            self.phase = 'ready'
            while self.running and not self._stop.is_set():
                started = time.monotonic()
                self.last_cycle_started = time.time()
                self.requests_this_cycle = 0
                self.stats = self._fresh_stats()
                self.last_reasons = Counter()
                try:
                    await self._cycle(db, client)
                    self.last_scan = time.time()
                    self.last_cycle_finished = self.last_scan
                    self.last_error = ''
                    self.rate_limited_until = None
                    self.phase = 'waiting'
                except RateLimitError as exc:
                    self.rate_limited_until = time.time() + exc.retry_after
                    self.last_error = f'CSFloat rate limited; cooling down {int(exc.retry_after)}s'
                    self.phase = 'rate-limited'
                    await notify_rate_limited(exc.retry_after, context='scan cycle')
                    await self._sleep(exc.retry_after)
                    continue
                except CSFloatAPIError as exc:
                    self.last_error = str(exc)
                    self.phase = 'api-error'
                    log.exception('API error during scan cycle')
                    await self._sleep(min(90, settings.poll_seconds))
                    continue
                except Exception as exc:
                    self.last_error = f'{type(exc).__name__}: {exc}'
                    self.phase = 'error'
                    log.exception('scan cycle failed')
                    await self._sleep(min(90, settings.poll_seconds))
                    continue
                self.db_counts = await counts(db)
                self.total_requests = client.request_count
                await self._sleep(max(2, settings.poll_seconds - (time.monotonic() - started)))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'
            self.phase = 'fatal'
            log.exception('scanner worker failed')
        finally:
            self.running = False
            if db:
                await db.close()
            await client.close()
            self.client = None
            if self.phase not in ('rate-limited', 'fatal'):
                self.phase = 'stopped'

    async def _sleep(self, seconds):
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, seconds))
        except asyncio.TimeoutError:
            pass

    async def _count_request(self, client):
        self.requests_this_cycle = client.request_count - getattr(self, '_cycle_request_base', 0)
        self.total_requests = client.request_count

    @staticmethod
    def _rank_key(listing):
        item = listing.get('item') or {}
        price = int(listing.get('price') or 10**9)
        ref = item.get('reference') or listing.get('reference') or {}
        predicted = ref.get('predicted_price') or ref.get('base_price') or 0
        discount = ((predicted - price) / predicted) if predicted else 0.0
        recent = listing.get('created_at') or ''
        return (discount, price == 0, -price, recent)

    async def _cycle(self, db, client):
        self._cycle_request_base = client.request_count
        combined = []

        if not settings.auctions_only:
            self.phase = 'scan-new-bin'
            newest, _ = await client.listings('buy_now', 'most_recent', settings.page_limit,
                                              min_price=settings.min_scan_price_cents, max_price=settings.max_scan_price_cents)
            await self._count_request(client)
            await upsert_listings(db, newest)
            combined.extend(newest or [])

            self.phase = 'scan-discounts'
            discounted, _ = await client.listings('buy_now', 'highest_discount', settings.page_limit,
                                                   min_price=settings.min_scan_price_cents, max_price=settings.max_scan_price_cents)
            await self._count_request(client)
            await upsert_listings(db, discounted)
            combined.extend(discounted or [])

        self.phase = 'scan-auctions'
        if not settings.enable_auctions and settings.auctions_only:
            self.phase = 'cycle-complete'
            return
        if settings.enable_auctions:
            cursor = None
            pages = settings.auction_pages_per_cycle if settings.auctions_only else 1
            for _ in range(max(1, pages)):
                auctions, cursor = await client.listings('auction', 'expires_soon', settings.page_limit,
                                                          cursor=cursor,
                                                          min_price=settings.min_scan_price_cents, max_price=settings.max_scan_price_cents)
                await self._count_request(client)
                await upsert_listings(db, auctions)
                combined.extend(auctions or [])
                self.stats['auction_pages_fetched'] += 1
                if not auctions or not cursor:
                    break

        # Deduplicate and prioritize cheap/discounted candidates.
        seen = set(); name_counts = Counter(); candidates = []
        for listing in sorted(combined, key=self._rank_key, reverse=True):
            lid = str(listing.get('id') or '')
            price = listing.get('price')
            item = listing.get('item') or {}
            name = str(item.get('market_hash_name') or '')
            if not lid or lid in seen or price is None or not name:
                continue
            seen.add(lid)
            if await is_blacklisted(db, name):
                self.stats['blacklisted'] += 1
                continue
            kind = kind_from(item)
            enabled = {
                'skin': settings.include_skins,
                'sticker': settings.include_stickers,
                'case': settings.include_cases,
                'charm': settings.include_charms,
                'key': settings.include_keys,
            }
            if not enabled.get(kind, True):
                continue
            if name_counts[name] >= settings.max_candidates_per_name:
                continue
            if settings.exclude_souvenirs and (item.get('is_souvenir') is True or name.startswith('Souvenir ')):
                self.stats['souvenirs_excluded'] += 1
                continue
            if price > settings.max_buy_price_usd * 100:
                self.stats['above_max_price'] += 1
                continue
            candidates.append(listing)
            name_counts[name] += 1
            if listing.get('type') == 'auction':
                self.stats['auction_candidates'] += 1
            else:
                self.stats['bin_candidates'] += 1
            if len(candidates) >= settings.max_candidates_per_cycle:
                break
        self.stats['seen'] = len(candidates)
        self.recent_candidates = []

        # Step 1, evaluate listings against others
        evaluations = []  
        for listing in candidates:
            lid = str(listing['id'])
            if await alert_sent(db, lid):
                self.stats['skipped_alerted'] += 1
                continue
            item = listing.get('item') or {}
            name = item.get('market_hash_name')
            comps = await active_comparables_escalating(db, name, lid, base_days=settings.comparables_lookback_days)
            obs = await observations(db, name, settings.history_days)
            sales_broad = await historical_sales(db, name, settings.history_days)
            sales_recent = await historical_sales(db, name, settings.sales_lookback_days)
            seed = await same_seed_prices(db, name, item.get('paint_seed'), settings.history_days)
            floats = await float_samples(db, name, settings.history_days)
            v = evaluate(listing, comps, obs, sales_broad, seed, floats, liquidity_sales_rows=sales_recent)
            if v:
                self.stats['valued'] += 1
                evaluations.append((v, listing, comps, obs, sales_broad, sales_recent, seed, floats))
                if not v.get('liquidity_ok', True):
                    self.stats['threshold_rejects'] += 1
                self.recent_candidates.append({
                    'id': lid, 'name': v['name'], 'kind': v.get('kind'), 'wear_tier': v.get('wear_tier'),
                    'price_cents': v['price_cents'], 'effective_buy_cents': v['effective_buy_cents'], 'fair_cents': v['fair_cents'],
                    'net_cents': v['net_cents'], 'profit_cents': v['profit_cents'], 'roi': v['roi'],
                    'confidence': v['confidence'], 'reason': v.get('reason',''), 'sales': v['recent_sales_points'],
                    'sales_required': v.get('recent_sales_required', settings.min_recent_sales),
                    'comparables': v['comparables'], 'listing_type': v['listing_type'],
                    'scm_price_cents': v.get('scm_price_cents'), 'scm_volume': v.get('scm_volume'),
                    'steam_capped': v.get('steam_capped', False),
                    'url': f'https://csfloat.com/item/{lid}'
                })

        # Step 2 Check for listings that match requirements but don't have enough comparables yet, and fetch those comparables to improve the evaluation.
        if evaluations and settings.max_comparable_lookups_per_cycle > 0:
            needs_comps = sorted(
                (row for row in evaluations if len(row[2]) < 3),
                key=lambda row: row[0]['profit_cents'], reverse=True
            )[:settings.max_comparable_lookups_per_cycle]
            for row in needs_comps:
                if self._stop.is_set():
                    break
                v, listing, comps, obs, sales_broad, sales_recent, seed, floats = row
                self.phase = 'focused-comparables'
                focused, _ = await client.listings('buy_now', 'lowest_price', settings.page_limit,
                                                    market_hash_name=v['name'], min_price=0)
                await self._count_request(client)
                self.stats['comparable_lookups'] += 1
                await upsert_listings(db, focused)
                merged = [int(x.get('price')) for x in focused or [] if x.get('price') is not None and str(x.get('id')) != str(listing['id'])]
                if merged:
                    new_v = evaluate(listing, merged, obs, sales_broad, seed, floats, liquidity_sales_rows=sales_recent) or v
                    for pos, existing in enumerate(evaluations):
                        if existing[1] is listing:
                            evaluations[pos] = (new_v, listing, merged, obs, sales_broad, sales_recent, seed, floats)
                            break
                    for cand in self.recent_candidates:
                        if cand['id'] == str(listing['id']):
                            cand['comparables'] = new_v['comparables']
                            cand['fair_cents'] = new_v['fair_cents']; cand['profit_cents'] = new_v['profit_cents']
                            cand['roi'] = new_v['roi']; cand['confidence'] = new_v['confidence']; cand['reason'] = new_v.get('reason', '')
                            cand['steam_capped'] = new_v.get('steam_capped', False)
                            break

        # Step 3, fetch historical sales to find the best past listings to improve the evaluation part
        fetch_budget = settings.max_historical_fetches_per_cycle
        if fetch_budget > 0 and evaluations:
            profit_by_name = {}
            for v, *_ in evaluations:
                profit_by_name[v['name']] = max(profit_by_name.get(v['name'], -10**9), v['profit_cents'])
            by_profit = sorted(profit_by_name.keys(), key=lambda n: profit_by_name[n], reverse=True)
            fetch_order = await fetch_priority_rank(db, by_profit)
            for name in fetch_order:
                if fetch_budget <= 0 or self._stop.is_set():
                    break
                if await sales_fresh(db, name, settings.sales_cache_hours):
                    continue
                matching = [row for row in evaluations if row[1].get('item', {}).get('market_hash_name') == name]
                if not matching:
                    continue
                self.phase = 'historical-fetch'
                paint_index = (matching[0][1].get('item') or {}).get('paint_index')
                raw = await client.sales_history(name, 100, paint_index)
                await self._count_request(client)
                self.stats['history_fetches'] += 1
                fetch_budget -= 1
                await save_sales(db, name, raw)
                await mark_sales_fetch(db, name, len(raw))
                fresh_broad = await historical_sales(db, name, settings.history_days)
                fresh_recent = await historical_sales(db, name, settings.sales_lookback_days)
                for v, listing, comps, obs, _old_broad, _old_recent, seed, floats in matching:
                    new_v = evaluate(listing, comps, obs, fresh_broad, seed, floats, liquidity_sales_rows=fresh_recent)
                    if new_v:
                        for pos, existing in enumerate(evaluations):
                            if existing[1] is listing:
                                evaluations[pos] = (new_v, listing, comps, obs, fresh_broad, fresh_recent, seed, floats)
                                break
                        for cand in self.recent_candidates:
                            if cand['id'] == str(listing['id']):
                                cand['sales'] = new_v['recent_sales_points']; cand['fair_cents'] = new_v['fair_cents']
                                cand['profit_cents'] = new_v['profit_cents']; cand['roi'] = new_v['roi']
                                cand['confidence'] = new_v['confidence']; cand['reason'] = new_v.get('reason', '')
                                cand['steam_capped'] = new_v.get('steam_capped', False)
                                break

        # Final alert pass.
        evaluations.sort(key=lambda t: (t[0]['profit_cents'], t[0]['confidence']), reverse=True)
        self.recent_candidates = sorted(self.recent_candidates, key=lambda x: x['profit_cents'], reverse=True)[:40]
        for v, listing, comps, obs, sales_broad, sales_recent, seed, floats in evaluations:
            if self._stop.is_set():
                break
            if is_opportunity(v):
                self.stats['opportunities'] += 1
                if await recent_alert_count(db) < settings.max_alerts_per_hour:
                    try:
                        self.phase = 'discord-alert'
                        await send_discord(listing, v)
                        await save_alert(db, listing['id'], v, 'qualifying flip')
                        self.stats['alerts_sent'] += 1
                        log.info('ALERT %s +$%.2f %s%%', v['name'], v['profit_cents']/100, v['roi'])
                    except Exception as exc:
                        self.stats['discord_failures'] += 1
                        self.last_error = f'Discord alert failed: {type(exc).__name__}: {exc}'
                        log.warning('Discord alert failed: %s', exc)
            else:
                self.stats['threshold_rejects'] += 1
                self.last_reasons[v.get('reason', 'unknown')] += 1
        self.phase = 'cycle-complete'
        self.db_counts = await counts(db)
        self.total_requests = client.request_count