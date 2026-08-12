"""Environment-based configuration for DharmaPostAI Bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when a required runtime configuration value is unavailable."""


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Invalid boolean value: {value!r}")


def _as_int(value: str | None, default: int, name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer.") from error
    if parsed < 1:
        raise ConfigurationError(f"{name} must be at least 1.")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    """All settings required by the application."""

    gemini_api_key: str
    gemini_model: str
    supabase_url: str
    supabase_service_role_key: str
    facebook_page_id: str
    facebook_page_access_token: str
    facebook_graph_api_version: str
    timezone_name: str
    post_time: str
    auto_publish: bool
    require_approval: bool
    poster_output_dir: Path
    font_path: Path
    max_daily_posts: int
    port: int
    log_level: str

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception as error:
            raise ConfigurationError(f"TIMEZONE is invalid: {self.timezone_name}") from error

    @property
    def post_hour_and_minute(self) -> tuple[int, int]:
        try:
            hour_text, minute_text = self.post_time.split(":", maxsplit=1)
            hour, minute = int(hour_text), int(minute_text)
        except ValueError as error:
            raise ConfigurationError("POST_TIME must use the HH:MM format, such as 07:00.") from error
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ConfigurationError("POST_TIME must be a valid 24-hour time.")
        return hour, minute

    def validate_for_generation(self) -> None:
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if missing:
            raise ConfigurationError("Missing required setting(s): " + ", ".join(missing))

    def validate_for_publishing(self) -> None:
        self.validate_for_generation()
        missing = []
        if not self.facebook_page_id:
            missing.append("FACEBOOK_PAGE_ID")
        if not self.facebook_page_access_token:
            missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
        if missing:
            raise ConfigurationError("Missing required setting(s): " + ", ".join(missing))


def load_settings() -> Settings:
    """Load settings from a local .env file and process environment variables."""
    load_dotenv(override=False)
    root = Path.cwd()
    output_dir = Path(os.getenv("POSTER_OUTPUT_DIR", "output"))
    font_path = Path(os.getenv("FONT_PATH", "Battambang-Bold.ttf"))

    port = _as_int(os.getenv("PORT"), 8080, "PORT")
    if port > 65535:
        raise ConfigurationError("PORT cannot exceed 65535.")

    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        facebook_page_id=os.getenv("FACEBOOK_PAGE_ID", "").strip(),
        facebook_page_access_token=os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "").strip(),
        facebook_graph_api_version=os.getenv("FACEBOOK_GRAPH_API_VERSION", "v26.0").strip(),
        timezone_name=os.getenv("TIMEZONE", "Asia/Phnom_Penh").strip(),
        post_time=os.getenv("POST_TIME", "07:00").strip(),
        auto_publish=_as_bool(os.getenv("AUTO_PUBLISH"), False),
        require_approval=_as_bool(os.getenv("REQUIRE_APPROVAL"), True),
        poster_output_dir=(root / output_dir).resolve(),
        font_path=(root / font_path).resolve(),
        max_daily_posts=_as_int(os.getenv("MAX_DAILY_POSTS"), 1, "MAX_DAILY_POSTS"),
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper().strip(),
    )
