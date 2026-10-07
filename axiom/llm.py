"""Resilient OpenRouter / MiniMax client — Contract 4.

The LLM does exactly two things in AXIOM: compile a clinician's question into a
query plan, and extract structured facts from prose notes. It runs on a free,
rate-limited tier in front of a live demo. Resilience is the whole point:

  * disk cache  — a cache hit never touches the network
  * 3 attempts  — 1s / 2s / 4s exponential backoff on 429, 5xx and timeouts
  * JSON repair — markdown fences stripped, then one stricter retry
  * no secrets  — the API key never reaches an exception, a log line or stdout

Stdlib only: urllib.request, hashlib, json. No httpx, no openai SDK.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

__all__ = ["LLMUnavailable", "LLMClient", "PROVIDERS"]


class LLMUnavailable(RuntimeError):
    """Raised when the LLM cannot produce a usable response.

    Never carries the API key, a header, or any fragment of the auth material.
    """


# ---------------------------------------------------------------- config --

PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
        "env_model": "OPENROUTER_MODEL",
        "default_model": "google/gemini-2.0-flash-001",
    },
    "minimax": {
        "endpoint": "https://api.minimax.io/v1/chat/completions",
        "env_key": "MINIMAX_API_KEY",
        "env_model": "MINIMAX_MODEL",
        "default_model": "MiniMax-Text-01",
    },
}

BACKOFF_SECONDS = (1, 2, 4)   # slept after attempt 1, 2, 3
MAX_ATTEMPTS = 3

_AUTH_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}")

STRICT_SUFFIX = (
    "\n\nIMPORTANT: Respond with a single valid JSON object and nothing else. "
    "Do not use markdown code fences, do not add commentary before or after, "
    "and do not wrap the JSON in anything else."
)

try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv as _dotenv_load
    _DOTENV_AVAILABLE = True
except Exception:  # pragma: no cover
    _dotenv_load = None
    _DOTENV_AVAILABLE = False


# ---------------------------------------------------------- env plumbing --

def _env_path() -> Path:
    """Repo-root `.env` (axiom/llm.py -> repo root)."""
    return Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> None:
    """Load repo-root `.env` into `os.environ` without clobbering real env."""
    path = _env_path()
    if _DOTENV_AVAILABLE:
        try:
            _dotenv_load(str(path))
            return
        except Exception:
            pass  # fall through to the plain parser
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value


# ------------------------------------------------------------- transport --

def _sleep(seconds: float) -> None:
    """Indirection so tests can neutralise backoff without patching `time`."""
    time.sleep(seconds)


def _http_post(url: str, payload: dict, headers: dict, timeout: float):
    """POST JSON via stdlib urllib. Indirection point for tests."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for name, value in headers.items():
        req.add_header(name, value)
    return urllib.request.urlopen(req, timeout=timeout)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        code = getattr(exc, "code", 0) or 0
        return code == 429 or code >= 500
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError,
                        ConnectionError, http.client.HTTPException, OSError)):
        return True
    return False


def _error_detail(exc: BaseException) -> str:
    """Short, key-free description of a failure, safe for exception text."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {getattr(exc, 'code', '?')}"
    if isinstance(exc, socket.timeout):
        return "timeout"
    name = type(exc).__name__
    text = str(exc)
    if len(text) > 120:
        text = text[:120] + "..."
    return f"{name}: {text}" if text else name


# ------------------------------------------------------------ JSON utils --

def _strip_fences(text: str) -> str:
    """Remove a leading ```json / ``` fence and its closing fence."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _parse_json(text: str) -> Optional[dict]:
    """Best-effort parse to a dict. Returns None instead of raising."""
    if not isinstance(text, str):
        return None
    candidates = [_strip_fences(text)]
    bare = candidates[0]
    # Fall back to the outermost {...} span when the model wrapped it in prose.
    start, end = bare.find("{"), bare.rfind("}")
    if start != -1 and end > start:
        candidates.append(bare[start:end + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


# ----------------------------------------------------------------- client --

class LLMClient:
    """OpenAI-compatible chat client with a disk cache and hard failure isolation."""

    def __init__(self, provider=None, model=None, cache_dir=".llm_cache",
                 timeout=30.0):
        _load_env()

        name = (provider or "").strip().lower() or None
        if name is None:
            for candidate in ("openrouter", "minimax"):
                if os.environ.get(PROVIDERS[candidate]["env_key"], "").strip():
                    name = candidate
                    break
        if name is None:
            raise LLMUnavailable(
                "No LLM provider configured: set OPENROUTER_API_KEY or "
                "MINIMAX_API_KEY, or pass provider= explicitly."
            )
        if name not in PROVIDERS:
            raise LLMUnavailable(
                f"Unknown LLM provider {name!r}; expected one of "
                f"{sorted(PROVIDERS)}."
            )

        cfg = PROVIDERS[name]
        key = os.environ.get(cfg["env_key"], "").strip()
        if not key:
            raise LLMUnavailable(
                f"Provider {name!r} selected but {cfg['env_key']} is not set."
            )

        self.provider = name
        self.endpoint = cfg["endpoint"]
        self.model = model or os.environ.get(cfg["env_model"], "").strip() \
            or cfg["default_model"]
        self.cache_dir = Path(cache_dir)
        self.timeout = float(timeout)
        self._key = key
        self._auth_header = f"Bearer {key}"

    # -- properties -------------------------------------------------------

    @property
    def provider_name(self) -> str:
        """`"openrouter"` | `"minimax"` (never leaks anything else)."""
        return self.provider

    # -- key hygiene ------------------------------------------------------

    def _scrub(self, text: str) -> str:
        """Defence in depth: strip the key from anything we might surface."""
        if not text:
            return ""
        if self._key:
            text = text.replace(self._key, "***")
            text = text.replace(self._key.strip(), "***")
        # Any Authorization-looking material, wherever it came from.
        return _AUTH_RE.sub("Bearer ***", text)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

    # -- cache ------------------------------------------------------------

    def _cache_key(self, system: str, user: str) -> str:
        blob = f"{self.provider}{self.model}{system}{user}".encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _cache_read(self, key: str) -> Optional[dict]:
        path = self._cache_path(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        value = _parse_json(raw)
        return value

    def _cache_write(self, key: str, value: dict) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path(key).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(value), encoding="utf-8")
            tmp.replace(self._cache_path(key))
        except OSError:
            pass  # a cache we cannot write is a performance problem, not a bug

    # -- network ----------------------------------------------------------

    def _content(self, system: str, user: str) -> str:
        """One model turn with transport retries. Returns the raw text."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        headers = self._headers()
        last: Optional[BaseException] = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                with _http_post(self.endpoint, payload, headers,
                                self.timeout) as resp:
                    body = resp.read()
                envelope = json.loads(body.decode("utf-8", errors="replace"))
                choices = envelope.get("choices") or []
                message = choices[0].get("message") or {}
                content = message.get("content")
                if not isinstance(content, str):
                    raise LLMUnavailable(
                        f"{self.provider} returned no message content.")
                return content
            except LLMUnavailable:
                raise
            except json.JSONDecodeError as exc:
                # A non-JSON envelope is a permanent protocol problem: do not
                # hammer a free tier for it.
                raise LLMUnavailable(
                    f"{self.provider} returned a non-JSON response "
                    f"({exc.msg}).") from None
            except BaseException as exc:  # noqa: BLE001 - isolation on purpose
                if not _is_retryable(exc):
                    raise LLMUnavailable(
                        f"{self.provider} request failed: "
                        f"{self._scrub(_error_detail(exc))}") from None
                last = exc
                # Backoff after every failed attempt: 1s, 2s, 4s. The pause
                # after the final failure buys nothing but keeps the schedule
                # honest and uniform.
                _sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

        detail = self._scrub(_error_detail(last)) if last else "unknown error"
        raise LLMUnavailable(
            f"{self.provider} unavailable after {MAX_ATTEMPTS} attempts: "
            f"{detail}") from None

    def _turn(self, system: str, user: str) -> dict:
        """One turn plus a single JSON-repair turn. Never returns junk."""
        value = _parse_json(self._content(system, user))
        if value is not None:
            return value

        # One stricter retry, then give up rather than spend more quota.
        repaired = _parse_json(self._content(system, user + STRICT_SUFFIX))
        if repaired is not None:
            return repaired

        raise LLMUnavailable(
            f"{self.provider} did not return a JSON object after a "
            f"repair attempt.")

    # -- public API -------------------------------------------------------

    def json(self, system: str, user: str) -> dict:
        """Return parsed JSON for (system, user). Raises LLMUnavailable."""
        key = self._cache_key(system, user)
        cached = self._cache_read(key)
        if cached is not None:
            return cached
        value = self._turn(system, user)
        self._cache_write(key, value)
        return value