"""Central configuration. Everything is env-driven so the same image runs
locally, in Docker, or on a managed host."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "screenshots").mkdir(exist_ok=True)
(DATA_DIR / "reports").mkdir(exist_ok=True)


@dataclass
class Settings:
    # --- server ---------------------------------------------------------
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _int("PORT", 8000)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    api_keys: list[str] = field(
        default_factory=lambda: [
            k.strip() for k in os.getenv("API_KEYS", "demo-key").split(",") if k.strip()
        ]
    )
    require_auth: bool = _bool("REQUIRE_AUTH", True)

    # --- storage --------------------------------------------------------
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/seoagent.db")
    data_dir: Path = DATA_DIR

    # --- crawl behaviour ------------------------------------------------
    max_pages: int = _int("MAX_PAGES", 10)
    crawl_concurrency: int = _int("CRAWL_CONCURRENCY", 5)
    request_timeout: int = _int("REQUEST_TIMEOUT", 20)
    per_host_delay_ms: int = _int("PER_HOST_DELAY_MS", 250)
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (compatible; SEOAuditAgent/1.0; +https://example.com/bot)",
    )
    respect_robots: bool = _bool("RESPECT_ROBOTS", True)
    max_link_checks: int = _int("MAX_LINK_CHECKS", 120)

    # --- throughput -----------------------------------------------------
    worker_count: int = _int("WORKER_COUNT", 4)
    daily_audit_quota: int = _int("DAILY_AUDIT_QUOTA", 500)
    audit_timeout_sec: int = _int("AUDIT_TIMEOUT_SEC", 600)

    # --- optional integrations -----------------------------------------
    psi_api_key: str = os.getenv("PAGESPEED_API_KEY", "")
    serper_api_key: str = os.getenv("SERPER_API_KEY", "")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    google_cse_id: str = os.getenv("GOOGLE_CSE_ID", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openpagerank_key: str = os.getenv("OPENPAGERANK_API_KEY", "")
    dataforseo_login: str = os.getenv("DATAFORSEO_LOGIN", "")
    dataforseo_password: str = os.getenv("DATAFORSEO_PASSWORD", "")

    # --- features -------------------------------------------------------
    screenshots_enabled: bool = _bool("SCREENSHOTS_ENABLED", True)
    screenshot_max: int = _int("SCREENSHOT_MAX", 12)
    competitors_enabled: bool = _bool("COMPETITORS_ENABLED", True)
    competitor_count: int = _int("COMPETITOR_COUNT", 3)
    pdf_enabled: bool = _bool("PDF_ENABLED", True)
    stateless: bool = _bool("STATELESS", False)

    # --- public mode (open link, no API key) ----------------------------
    rate_limit_per_hour: int = _int("RATE_LIMIT_PER_HOUR", 5)
    report_cache_minutes: int = _int("REPORT_CACHE_MINUTES", 30)
    report_cache_max: int = _int("REPORT_CACHE_MAX", 25)
    public_max_pages: int = _int("PUBLIC_MAX_PAGES", 8)

    @property
    def public_mode(self) -> bool:
        """Anyone with the link can run an audit."""
        return not self.require_auth

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
