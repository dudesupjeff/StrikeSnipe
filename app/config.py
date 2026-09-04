from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore', case_sensitive=False)
    csfloat_api_key: str = ''
    discord_webhook_url: str = ''

    max_buy_price_usd: float = 5.00
    min_buy_price_usd: float = 0.05
    min_profit_usd: float = 0.10        
    min_roi_percent: float = 1.0
    min_discount_percent: float = 1.0
    min_confidence: int = 45
    max_alerts_per_hour: int = 30
    seller_fee_rate: float = 0.02
    exit_safety_usd: float = 0.02
    exclude_souvenirs: bool = True
    exclude_stickered: bool = False
    include_normal: bool = True
    include_stattrak: bool = True
    include_skins: bool = True
    include_stickers: bool = True
    include_cases: bool = True
    include_charms: bool = True
    include_keys: bool = True

    enable_auctions: bool = True
    auctions_only: bool = False
    auction_min_minutes: int = 1
    auction_max_minutes: int = 128      
    auction_pages_per_cycle: int = 2     
    poll_seconds: int = 180
    request_min_interval_seconds: float = 8.0
    request_jitter_seconds: float = 1.0
    retry_after_floor_seconds: int = 180
    request_timeout_seconds: float = 20.0
    page_limit: int = 50
    max_candidates_per_cycle: int = 30
    max_candidates_per_name: int = 3
    max_comparable_lookups_per_cycle: int = 6     
    max_historical_fetches_per_cycle: int = 8     
    sales_cache_hours: float = 12.0             
    history_days: int = 30
    comparables_lookback_days: int = 7            
    min_recent_sales: int = 5             
    sales_lookback_days: int = 7
    min_recent_sales_for_strong_confidence: int = 5
    min_scan_price_cents: int = 5
    max_scan_price_cents: int = 0
    database_path: str = 'data/strikesnipe.db'
    user_agent: str = 'StrikeSnipe/3.1 (manual-alert-only)'

settings = Settings()
settings.max_buy_price_usd=max(0.01,float(settings.max_buy_price_usd))
settings.min_buy_price_usd=max(0.00,min(float(settings.min_buy_price_usd),settings.max_buy_price_usd))
settings.min_profit_usd=max(0.01,float(settings.min_profit_usd))
settings.min_roi_percent=max(0.0,float(settings.min_roi_percent))
settings.min_discount_percent=max(0.0,float(settings.min_discount_percent))
settings.min_confidence=min(100,max(0,int(settings.min_confidence)))
settings.max_alerts_per_hour=max(1,int(settings.max_alerts_per_hour))
settings.poll_seconds=max(30,int(settings.poll_seconds))
settings.request_min_interval_seconds=max(1.0,float(settings.request_min_interval_seconds))
settings.page_limit=min(50,max(1,int(settings.page_limit)))
settings.max_candidates_per_cycle=max(1,int(settings.max_candidates_per_cycle))
settings.max_candidates_per_name=max(1,int(settings.max_candidates_per_name))
settings.max_comparable_lookups_per_cycle=max(0,int(settings.max_comparable_lookups_per_cycle))
settings.max_historical_fetches_per_cycle=max(0,int(settings.max_historical_fetches_per_cycle))
settings.auction_pages_per_cycle=min(4,max(1,int(settings.auction_pages_per_cycle)))
settings.auction_min_minutes=max(0,int(settings.auction_min_minutes))
settings.auction_max_minutes=max(settings.auction_min_minutes+1,int(settings.auction_max_minutes))
settings.exit_safety_usd=max(0.0,float(settings.exit_safety_usd))
settings.min_recent_sales=max(0,int(settings.min_recent_sales))
settings.sales_lookback_days=max(1,int(settings.sales_lookback_days))
settings.comparables_lookback_days=max(1,int(settings.comparables_lookback_days))
settings.min_scan_price_cents=max(0,int(round(settings.min_buy_price_usd*100)))
raw_max=int(settings.max_scan_price_cents)
settings.max_scan_price_cents=int(round(settings.max_buy_price_usd*100))+1 if raw_max<=0 else min(int(round(settings.max_buy_price_usd*100))+1,raw_max)
settings.max_scan_price_cents=max(settings.min_scan_price_cents+1,settings.max_scan_price_cents)
