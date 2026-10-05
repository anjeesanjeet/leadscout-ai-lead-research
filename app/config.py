"""Central configuration, loaded from environment variables / .env file."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _optional_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return float(raw) if raw else None


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "anthropic").lower())
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4.1-mini"))
    temperature: float | None = field(default_factory=lambda: _optional_float("LLM_TEMPERATURE", None))
    anthropic_price_input: float = field(default_factory=lambda: _float("ANTHROPIC_PRICE_INPUT_PER_MTOK", 1.0))
    anthropic_price_output: float = field(default_factory=lambda: _float("ANTHROPIC_PRICE_OUTPUT_PER_MTOK", 5.0))
    openai_price_input: float = field(default_factory=lambda: _float("OPENAI_PRICE_INPUT_PER_MTOK", 0.40))
    openai_price_output: float = field(default_factory=lambda: _float("OPENAI_PRICE_OUTPUT_PER_MTOK", 1.60))

    # --- Research ---
    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    tavily_price_per_search: float = field(default_factory=lambda: _float("TAVILY_PRICE_PER_SEARCH", 0.008))
    max_pages: int = field(default_factory=lambda: _int("MAX_PAGES", 4))
    page_char_limit: int = field(default_factory=lambda: _int("PAGE_CHAR_LIMIT", 6000))
    request_timeout: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT", 15.0))
    user_agent: str = field(default_factory=lambda: _env(
        "USER_AGENT", "Mozilla/5.0 (compatible; LeadScoutBot/1.0; public company research)"))

    # --- Scoring / drafting ---
    fit_threshold: float = field(default_factory=lambda: _float("FIT_THRESHOLD", 6.0))
    grounding_min_score: float = field(default_factory=lambda: _float("GROUNDING_MIN_SCORE", 90.0))

    # --- Sinks ---
    hubspot_token: str = field(default_factory=lambda: _env("HUBSPOT_TOKEN"))
    google_service_account_file: str = field(default_factory=lambda: _env("GOOGLE_SERVICE_ACCOUNT_FILE"))
    google_sheet_id: str = field(default_factory=lambda: _env("GOOGLE_SHEET_ID"))

    # --- Server ---
    api_key: str = field(default_factory=lambda: _env("LEADSCOUT_API_KEY"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL", "http://127.0.0.1:8100").rstrip("/"))
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8100))

    # --- Paths ---
    db_path: Path = field(default_factory=lambda: ROOT_DIR / _env("DB_PATH", "data/leadscout.db"))
    outputs_dir: Path = field(default_factory=lambda: ROOT_DIR / "outputs")
    config_dir: Path = field(default_factory=lambda: ROOT_DIR / "config")

    @property
    def eval_results_path(self) -> Path:
        return self.outputs_dir / "eval_results.json"

    @property
    def leads_csv_path(self) -> Path:
        return self.outputs_dir / "leads.csv"

    @property
    def model_name(self) -> str:
        return self.anthropic_model if self.llm_provider.startswith(("anthropic", "claude")) else self.openai_model

    def icp(self) -> dict:
        return json.loads((self.config_dir / "icp.json").read_text(encoding="utf-8"))

    def sender(self) -> dict:
        return json.loads((self.config_dir / "sender.json").read_text(encoding="utf-8"))


def get_settings() -> Settings:
    return Settings()
