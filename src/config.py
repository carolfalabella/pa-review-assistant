"""Settings, read from environment variables or a local .env file.

The model provider is ONE setting (PROVIDER), so switching between Gemini,
local Ollama, and a saved run never needs code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is in requirements.txt; the app still works without it
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _float_or_none(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _bool_or_none(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    provider: str  # "gemini" | "ollama" | "saved"
    gemini_api_key: str | None
    gemini_model: str
    gemini_temperature: float | None  # None = use the model's default
    retry_waits: tuple[int, ...]  # seconds to wait before each retry of a busy response
    request_timeout: int
    ollama_url: str
    ollama_model: str
    ollama_think: bool | None  # None = don't send the setting
    ollama_num_ctx: int
    saved_run: Path | None
    runs_dir: Path
    receipt_time: str | None  # ISO time; None = the moment the packet is loaded

    def with_(self, **changes) -> "Settings":
        return replace(self, **changes)


def load_settings() -> Settings:
    # Short waits suit brief overloads (503). For quota limits (429) the
    # provider waits at least as long as the server asks, whatever this says.
    waits = _env("RETRY_WAITS", "5,10,20,40")
    saved = _env("SAVED_RUN")
    return Settings(
        provider=_env("PROVIDER", "gemini").lower(),
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=_env("GEMINI_MODEL", "gemini-3.6-flash"),
        gemini_temperature=_float_or_none(_env("GEMINI_TEMPERATURE")),
        retry_waits=tuple(int(w) for w in waits.split(",") if w.strip()),
        request_timeout=int(_env("REQUEST_TIMEOUT", "180")),
        ollama_url=_env("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env("OLLAMA_MODEL", "qwen3.5:4b"),
        ollama_think=_bool_or_none(_env("OLLAMA_THINK", "false")),
        ollama_num_ctx=int(_env("OLLAMA_NUM_CTX", "16384")),
        saved_run=(ROOT / saved) if saved else None,
        runs_dir=ROOT / _env("RUNS_DIR", "runs"),
        receipt_time=_env("DEMO_RECEIPT_TIME"),
    )
