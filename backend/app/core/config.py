import os
from urllib.parse import urlsplit

API_TITLE = "IndyOps API"
API_VERSION = "0.0.1"

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL")

ESI_CLIENT_ID = os.getenv("CLIENT_ID")
ESI_CLIENT_SECRET = os.getenv("CLIENT_SECRET")
ESI_CALLBACK_URL = os.getenv("CALLBACK_URL")

def _frontend_url() -> str:
    explicit = os.getenv("FRONTEND_URL")
    if explicit:
        return explicit.rstrip("/")
    if ESI_CALLBACK_URL:
        parts = urlsplit(ESI_CALLBACK_URL)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return "http://localhost:5173"

FRONTEND_URL = _frontend_url()

ESI_SCOPES = [
    "publicData",
    "esi-wallet.read_character_wallet.v1",
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-assets.read_assets.v1",
    "esi-contracts.read_character_contracts.v1",
    "esi-industry.read_character_jobs.v1",
    "esi-characters.read_standings.v1",
    # resolve Upwell-structure (citadel) names for asset locations — requires the
    # character to re-link once to grant it; structures fall back to their id otherwise
    "esi-universe.read_structures.v1",
    # character-page overview: current location/ship/online + active implants.
    # New scopes → characters must re-link once; unsynced fields fall back to '—'.
    "esi-location.read_location.v1",
    "esi-location.read_ship_type.v1",
    "esi-location.read_online.v1",
    "esi-clones.read_implants.v1",
    "esi-clones.read_clones.v1",
    # mining ledger → the per-character mining journal / profit report
    "esi-industry.read_character_mining.v1",
    # owned blueprints (BPOs/BPCs with ME/TE/runs) → Personal File Blueprints tab +
    # chain "what do I own / what's missing" report. New scope → characters re-link once.
    "esi-characters.read_blueprints.v1",
    # active market orders (buy/sell) → Tracking → Orders + the account dashboard.
    # New scope → characters must re-link once; orders stay empty until granted.
    "esi-markets.read_character_orders.v1",
    # planetary interaction colonies (planets + extractor/storage layout) → Tracking → PI.
    # New scope → characters must re-link once; colonies stay empty until granted.
    "esi-planets.manage_planets.v1",
    # CORPORATION (Phase B): real corp-level tracking — wallet/industry/members, gated by the
    # linking character's in-game roles (Director/Accountant/Factory Manager). A character
    # without the role still grants the scope but the corp endpoint returns 403, so corp data
    # only appears for corps where the user holds a sufficiently-roled character. Re-link once.
    "esi-characters.read_corporation_roles.v1",       # which corp roles the character holds
    "esi-wallet.read_corporation_wallets.v1",          # corp wallet division balances (Accountant)
    "esi-corporations.read_corporation_membership.v1", # corp member list (any member; Director-safe)
    "esi-industry.read_corporation_jobs.v1",           # corp-owned industry jobs (Factory Manager)
    # CORPORATION (Phase C): corp warehouses (assets) + contracts with their contents.
    # Assets + division names need the Director role; contracts need only the scope (any
    # member). Re-link once to grant; corp data only appears for corps where the user holds a
    # sufficiently-roled character.
    "esi-assets.read_corporation_assets.v1",           # corp assets — the corp warehouses (Director)
    "esi-corporations.read_divisions.v1",              # hangar / wallet division names (Director)
    "esi-contracts.read_corporation_contracts.v1",     # corp contracts + their items (any member)
]

ESI_USER_AGENT = os.getenv(
    "ESI_USER_AGENT",
    "IndyOps/1.0 (industrial manager; +https://github.com/niki8885/IndyOps)",
)

ESI_LOGIN_HOST = "https://login.eveonline.com"
ESI_AUTHORIZE_URL = f"{ESI_LOGIN_HOST}/v2/oauth/authorize"
ESI_TOKEN_URL = f"{ESI_LOGIN_HOST}/v2/oauth/token"
ESI_JWKS_URL = f"{ESI_LOGIN_HOST}/oauth/jwks"
ESI_TOKEN_ISSUERS = ("login.eveonline.com", "https://login.eveonline.com")
ESI_BASE_URL = "https://esi.evetech.net/latest"

SSO_STATE_EXPIRE_MINUTES = 15

# --- TRADE (cross-hub optimizer + station trading data layer) ---------------
# Tunable preprocessing thresholds — all env-overridable so they can be retuned
# in production without a code change.
TRADE_LIQUIDITY_MIN_VOLUME = int(os.getenv("TRADE_LIQUIDITY_MIN_VOLUME", "20"))   # daily traded units floor
TRADE_VOLATILITY_MAX_CV    = float(os.getenv("TRADE_VOLATILITY_MAX_CV", "0.15"))   # reject CV above this
TRADE_HISTORY_DAYS         = int(os.getenv("TRADE_HISTORY_DAYS", "14"))            # CV/volume lookback window
TRADE_BROKER_FEE           = float(os.getenv("TRADE_BROKER_FEE", "0.03"))          # 3% per order placed
TRADE_SALES_TAX            = float(os.getenv("TRADE_SALES_TAX", "0.045"))          # 4.5% on sale
TRADE_ISK_PER_JUMP_M3      = float(os.getenv("TRADE_ISK_PER_JUMP_M3", "1200"))     # courier rate ISK / (jump·m³)
TRADE_MIN_HUBS             = int(os.getenv("TRADE_MIN_HUBS", "2"))                 # require presence in ≥N hubs
TRADE_MIN_BOOK_VOLUME      = int(os.getenv("TRADE_MIN_BOOK_VOLUME", "50"))         # min order-book depth to consider
TRADE_MAX_UNIVERSE         = int(os.getenv("TRADE_MAX_UNIVERSE", "1500"))          # cap discovered types (bounds ESI)
TRADE_MAX_ORDER_PAGES      = int(os.getenv("TRADE_MAX_ORDER_PAGES", "300"))        # per-region order-book page cap
TRADE_TTL_SECONDS          = int(os.getenv("TRADE_TTL_SECONDS", "900"))            # candidate freshness (query layer)

# --- Jita → C-J6MT haul scanner (auto-discovery) ----------------------------
# Separate from the cross-hub optimizer: a focused, bounded scan of the most
# liquid Jita items priced against C-J (the C-J scrape is slow, so keep it small).
TRADE_HAUL_MIN_VOLUME  = int(os.getenv("TRADE_HAUL_MIN_VOLUME", "50"))    # Jita daily-volume floor
TRADE_HAUL_MAX_ITEMS   = int(os.getenv("TRADE_HAUL_MAX_ITEMS", "1000"))   # cap (bounds the C-J scrape)
TRADE_HAUL_SHIP_M3     = float(os.getenv("TRADE_HAUL_SHIP_M3", "1200"))   # default courier ISK/m³ for ranking
TRADE_HAUL_TTL_SECONDS = int(os.getenv("TRADE_HAUL_TTL_SECONDS", "3600")) # scanner freshness (query layer)

# The haul scanner's own category gate (separate from the cross-hub allowlist below):
# 6 Ship, 7 Module, 8 Charge, 18 Drone — NO Fighters (87, niche/illiquid for hauling).
TRADE_HAUL_CATEGORY_ALLOWLIST = {
    int(x) for x in os.getenv("TRADE_HAUL_CATEGORY_ALLOWLIST", "6,7,8,18").split(",") if x.strip()
}
# Extra SDE invGroups the haul scanner includes regardless of category — combat
# boosters ("Drugs"): group 303 "Booster" (category 20 Implant, which we don't want
# wholesale). Override with a CSV env var. Live-SDE verify: eve_groups.group_name='Booster'.
TRADE_HAUL_DRUG_GROUPS = {
    int(x) for x in os.getenv("TRADE_HAUL_DRUG_GROUPS", "303").split(",") if x.strip()
}

# --- Trade portfolio optimizer (Markowitz mean-variance, native Fortran) -----
# Risk aversion λ in max wᵀμ − (λ/2)·wᵀΣw (diagonal Σ); higher = more risk-averse.
TRADE_PORTFOLIO_RISK_AVERSION = float(os.getenv("TRADE_PORTFOLIO_RISK_AVERSION", "8.0"))
# Liquidity horizon (days) you expect to sell a position over (per-item qty cap).
TRADE_PORTFOLIO_HORIZON_DAYS  = int(os.getenv("TRADE_PORTFOLIO_HORIZON_DAYS", "7"))
# Fraction of an item's DAILY traded volume you can realistically capture (the C-J
# sell-side is thinner than Jita, so keep this low) — qty cap = participation·vol·days.
TRADE_PORTFOLIO_PARTICIPATION = float(os.getenv("TRADE_PORTFOLIO_PARTICIPATION", "0.10"))
# Diversification: max share of the budget a single item may take (with few items
# selected the effective cap floors at 1/N so the budget can still be deployed).
TRADE_PORTFOLIO_MAX_WEIGHT    = float(os.getenv("TRADE_PORTFOLIO_MAX_WEIGHT", "0.25"))
# Fallback return volatility when an item has no Jita price CV in trade_type_stats.
TRADE_PORTFOLIO_DEFAULT_SIGMA = float(os.getenv("TRADE_PORTFOLIO_DEFAULT_SIGMA", "0.15"))
# Floor on the per-item volatility fed to the optimizer, so a stable-priced arbitrage
# item isn't treated as riskless (which would make mean-variance dump the whole budget
# into it). Real risk here is liquidity, handled by the caps above.
TRADE_PORTFOLIO_MIN_SIGMA     = float(os.getenv("TRADE_PORTFOLIO_MIN_SIGMA", "0.05"))

# Market category_ids that may become trade candidates (SDE invCategories):
# 6 Ship, 7 Module, 8 Charge, 18 Drone, 87 Fighter. Excludes blueprints (9),
# skillbooks (16), SKINs (91), etc. Override with a CSV env var.
TRADE_CATEGORY_ALLOWLIST = {
    int(x) for x in os.getenv("TRADE_CATEGORY_ALLOWLIST", "6,7,8,18,87").split(",") if x.strip()
}

# --- Bank currency (Aureus / Penny) -----------------------------------------
# Players fund their in-app balance by donating ISK in-game to this corporation
# (wallet-journal ref_type 'player_donation'). Conversion: 1 ISK = 1 Aureus,
# 0.01 ISK = 1 Penny (100 Penny = 1 Aureus). If BANK_CORP_ID isn't set it's
# resolved once from the name via ESI /universe/ids/ and cached for the run.
BANK_CORP_NAME = os.getenv("BANK_CORP_NAME", "Miners and Merchants Bank")
BANK_CORP_ID = int(os.getenv("BANK_CORP_ID", "0")) or None