from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Environment variables (architecture.md §9). Secrets come only from env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_secret_key: str = ""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_lite_model: str = "gemini-flash-lite-latest"

    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_username: str = "huda_alert_bot"

    cron_secret: str = ""
    weatherapi_key: str = ""

    frontend_origin: str = "http://localhost:5173"
    public_site_url: str = "https://huda.netlify.app"

    model_path: Path = SERVER_DIR.parent / "ml" / "models" / "lgbm_v1.txt"
    radar_cache_dir: Path = Path("/tmp/huda_radar")
    # RainViewer tile options: {smooth}_{snow}. 0_0 decodes cleanly (implementation-plan §5.3).
    rainviewer_decode_options: str = "0_0"
    rainviewer_display_options: str = "1_1"
    # "auto" = pySTEPS if installed, else global shift. "global_shift" never loads pySTEPS (512 MB hosts).
    nowcast_method: str = "auto"

    # Dev-only failure drills, e.g. "open_meteo,gemini" (implementation-plan §6).
    fault_inject: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


class InjectedFault(RuntimeError):
    pass


def check_fault(name: str) -> None:
    """Raise if FAULT_INJECT names this source. Used by the Day-3 failure drills."""
    faults = {f.strip() for f in get_settings().fault_inject.split(",") if f.strip()}
    if name in faults:
        raise InjectedFault(f"fault injected: {name}")
