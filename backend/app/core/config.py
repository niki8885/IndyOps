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