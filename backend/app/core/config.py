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

# Market category_ids that may become trade candidates (SDE invCategories):
# 6 Ship, 7 Module, 8 Charge, 18 Drone, 87 Fighter. Excludes blueprints (9),
# skillbooks (16), SKINs (91), etc. Override with a CSV env var.
TRADE_CATEGORY_ALLOWLIST = {
    int(x) for x in os.getenv("TRADE_CATEGORY_ALLOWLIST", "6,7,8,18,87").split(",") if x.strip()
}