import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value

@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    database_url: str
    webhook_url: str
    webhook_secret: str
    claim_timeout_seconds: int = 120
    normal_radius_km: float = 1.0
    broadcast_radius_km: float = 5.0

def load_settings() -> Settings:
    admins = {
        int(x.strip())
        for x in _required("ADMIN_IDS").split(",")
        if x.strip()
    }
    return Settings(
        bot_token=_required("BOT_TOKEN"),
        admin_ids=admins,
        database_url=_required("DATABASE_URL"),
        webhook_url=_required("WEBHOOK_URL").rstrip("/"),
        webhook_secret=_required("WEBHOOK_SECRET"),
        claim_timeout_seconds=int(os.getenv("CLAIM_TIMEOUT_SECONDS", "120")),
        normal_radius_km=float(os.getenv("NORMAL_RADIUS_KM", "1.0")),
        broadcast_radius_km=float(os.getenv("BROADCAST_RADIUS_KM", "5.0")),
    )
