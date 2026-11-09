"""Model providers behind one interface: generate_json(call_name, system, user, schema).

- gemini: Gemini API generateContent over REST, with structured JSON output
- ollama: a local model through Ollama (fallback; no network needed)
- saved:  replays a recorded run from a file (fallback; clearly labeled)

The rest of the pipeline never knows which provider ran. The PROVIDER setting
picks one.

Security notes: the Gemini key goes in the x-goog-api-key header, never in the
URL, so it can't leak into logs or error messages that print the URL.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .config import Settings


class LLMError(Exception):
    """A provider call failed. The pipeline turns this into human review."""

    def __init__(self, message: str, attempts: int = 1, waited_seconds: float = 0.0):
        super().__init__(message)
        self.attempts = attempts
        self.waited_seconds = waited_seconds


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    seconds: float
    attempts: int = 1
    waited_seconds: float = 0.0
    usage: dict = field(default_factory=dict)
    label: str | None = None  # set for saved runs so the UI can never hide it


WaitCallback = Callable[[str, int, int, str], None]  # (call_name, attempt, wait_s, reason)


# --------------------------------------------------------------------- Gemini
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE = {429, 500, 502, 503, 504}
MAX_SINGLE_WAIT = 90  # never wait longer than this for one retry, whatever the server suggests


def gemini_error_info(status: int | None, body: str) -> dict:
    """Pull the useful parts out of a Google API error body.

    A 429 body names the quota that was hit (for example
    GenerateRequestsPerMinutePerProjectPerModel-FreeTier) and often a
    RetryInfo.retryDelay such as "37s". Retrying sooner than that wastes
    quota, which is what made the 5-second retries fail on Nov 7.
    """
    info = {"message": "", "quota_ids": [], "retry_delay": None, "daily": False}
    try:
        err = json.loads(body).get("error", {})
    except (ValueError, AttributeError):
        info["message"] = body.strip().splitlines()[0][:200] if body.strip() else ""
        return info
    info["message"] = (err.get("message") or "").strip().splitlines()[0][:200]
    for d in err.get("details") or []:
        kind = d.get("@type", "")
        if kind.endswith("QuotaFailure"):
            info["quota_ids"] += [v.get("quotaId", "") for v in d.get("violations") or []]
        elif kind.endswith("RetryInfo"):
            delay = str(d.get("retryDelay", "")).rstrip("s")
            try:
                info["retry_delay"] = float(delay)
            except ValueError:
                pass
    info["daily"] = any("PerDay" in q for q in info["quota_ids"])
    return info


def describe_gemini_error(status: int | None, info: dict) -> str:
    if status == 429 and info["daily"]:
        return ("daily free-tier quota used up (" + ", ".join(info["quota_ids"]) +
                "). It resets at midnight Pacific time.")
    if status == 429:
        quota = ", ".join(q for q in info["quota_ids"] if q) or "rate limit"
        return f"HTTP 429 quota limit ({quota})"
    if status == 503:
        return "HTTP 503 model overloaded"
    return f"HTTP {status}: {info['message']}" if status else info["message"]


def to_openapi_schema(schema: dict) -> dict:
    """Convert a JSON Schema to the older responseSchema (OpenAPI subset) form.
    Used only if the API rejects responseJsonSchema with HTTP 400."""
    out: dict = {}
    for key, value in schema.items():
        if key == "type":
            out["type"] = value.upper()
        elif key == "properties":
            out["properties"] = {k: to_openapi_schema(v) for k, v in value.items()}
            out["propertyOrdering"] = list(value.keys())
        elif key == "items":
            out["items"] = to_openapi_schema(value)
        elif key in ("required", "enum", "minimum", "description"):
            out[key] = value
    return out


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        temperature: float | None = None,
        retry_waits: tuple[int, ...] = (15, 30, 60, 120),
        timeout: int = 180,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_wait: WaitCallback | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.retry_waits = retry_waits
        self.timeout = timeout
        self.session = session or requests.Session()
        self.sleep = sleep
        self.on_wait = on_wait

    def _body(self, system: str, user: str, schema: dict, mode: str) -> dict:
        config: dict = {"responseMimeType": "application/json"}
        if mode == "responseJsonSchema":
            config["responseJsonSchema"] = schema
        else:
            config["responseSchema"] = to_openapi_schema(schema)
        if self.temperature is not None:
            config["temperature"] = self.temperature
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }

    def generate_json(self, call_name: str, system: str, user: str, schema: dict) -> LLMResponse:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to your local .env file.")
        url = f"{GEMINI_BASE}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        mode = "responseJsonSchema"
        attempts, retries_used, waited = 0, 0, 0.0
        start = time.monotonic()

        while True:
            attempts += 1
            status, info = None, {"message": "", "quota_ids": [], "retry_delay": None, "daily": False}
            try:
                r = self.session.post(
                    url, headers=headers, json=self._body(system, user, schema, mode), timeout=self.timeout
                )
                status = r.status_code
                if status == 200:
                    try:
                        return self._parse(r.json(), attempts, waited, time.monotonic() - start)
                    except LLMError as exc:
                        raise LLMError(str(exc), attempts, waited) from None
                info = gemini_error_info(status, r.text)
            except requests.RequestException as exc:
                info["message"] = f"network error ({type(exc).__name__})"  # no URL or key in the message
            problem = describe_gemini_error(status, info)

            if status == 400 and mode == "responseJsonSchema":
                mode = "responseSchema"  # documented fallback; does not count as a retry
                continue
            retryable = (status is None or status in RETRYABLE) and not info["daily"]
            if retryable and retries_used < len(self.retry_waits):
                # Wait at least as long as the server asks, so a retry doesn't burn quota.
                # The cap limits only the server's suggestion, never the configured schedule.
                suggested = min(info["retry_delay"] or 0, MAX_SINGLE_WAIT)
                wait = max(self.retry_waits[retries_used], suggested)
                retries_used += 1
                if self.on_wait:
                    self.on_wait(call_name, attempts, int(wait), problem)
                self.sleep(wait)
                waited += wait
                continue
            raise LLMError(f"Gemini call '{call_name}' failed after {attempts} attempt(s): {problem}",
                           attempts, waited)

    def _parse(self, data: dict, attempts: int, waited: float, seconds: float) -> LLMResponse:
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"Gemini returned no answer (promptFeedback: {data.get('promptFeedback')})")
        cand = candidates[0]
        finish = cand.get("finishReason")
        parts = (cand.get("content") or {}).get("parts") or []
        # Thinking models may return parts marked "thought"; those are not the answer.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if finish not in (None, "STOP"):
            raise LLMError(f"Gemini stopped early (finishReason: {finish})")
        return LLMResponse(
            text=text,
            provider=self.name,
            model=data.get("modelVersion") or self.model,
            seconds=round(seconds, 2),
            attempts=attempts,
            waited_seconds=waited,
            usage=data.get("usageMetadata") or {},
        )


# --------------------------------------------------------------------- Ollama
class OllamaProvider:
    name = "ollama"

    def __init__(self, url: str, model: str, think: bool | None = False, num_ctx: int = 16384,
                 timeout: int = 600, session: requests.Session | None = None):
        self.url = url
        self.model = model
        self.think = think
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.session = session or requests.Session()

    def generate_json(self, call_name: str, system: str, user: str, schema: dict) -> LLMResponse:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
        }
        if self.think is not None:
            body["think"] = self.think
        start = time.monotonic()
        try:
            r = self.session.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LLMError(f"Ollama is not reachable at {self.url} ({type(exc).__name__}). Is it running?")
        if r.status_code != 200:
            raise LLMError(f"Ollama call '{call_name}' failed: HTTP {r.status_code} {r.text[:300]}")
        data = r.json()
        return LLMResponse(
            text=(data.get("message") or {}).get("content", ""),
            provider=self.name,
            model=data.get("model") or self.model,
            seconds=round(time.monotonic() - start, 2),
            usage={"prompt_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")},
        )


# ---------------------------------------------------------------- Saved run
class SavedProvider:
    """Replays the raw model responses recorded in a saved-run file.

    The code checks still run live on the replayed responses, so a saved run
    still shows real quote verification. Every result carries a SAVED RUN label.
    """

    name = "saved"

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise LLMError(f"Saved run not found: {self.path}")
        with open(self.path, encoding="utf-8") as f:
            self.record = json.load(f)
        self.packet_sha256 = self.record.get("packet_sha256")
        src = self.record.get("source", {})
        self.model = f"{src.get('provider', '?')}/{src.get('model', '?')}"
        # The label always starts with "SAVED RUN", whatever the file's own label says,
        # so a replay can never be mistaken for a live call.
        tag = self.record.get("label")
        self.label = (
            "SAVED RUN" + (f" ({tag})" if tag and tag != "SAVED RUN" else "")
            + f": recorded {self.record.get('created_at', '?')} from {self.model}. Not a live model call."
        )

    def generate_json(self, call_name: str, system: str, user: str, schema: dict) -> LLMResponse:
        responses = self.record.get("responses", {})
        if call_name not in responses:
            raise LLMError(f"Saved run has no recorded response for '{call_name}'")
        return LLMResponse(text=responses[call_name], provider=self.name, model=self.model,
                           seconds=0.0, label=self.label)


def make_provider(settings: Settings, on_wait: WaitCallback | None = None):
    if settings.provider == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.gemini_temperature,
                              settings.retry_waits, settings.request_timeout, on_wait=on_wait)
    if settings.provider == "ollama":
        return OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_think,
                              settings.ollama_num_ctx)
    if settings.provider == "saved":
        if not settings.saved_run:
            raise LLMError("PROVIDER=saved needs SAVED_RUN set to a saved-run file")
        return SavedProvider(settings.saved_run)
    raise LLMError(f"Unknown PROVIDER '{settings.provider}'. Use gemini, ollama, or saved.")
