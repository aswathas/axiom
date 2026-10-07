"""Tests for axiom.llm — LLMClient (Contract 4).

NO REAL NETWORK CALLS in any test. The HTTP layer is monkeypatched.

TDD order (each test below was written before the implementation it covers):
  1. provider resolution + construction failure
  2. cache miss calls network / cache hit does not
  3. markdown fence stripping
  4. retry on 429 -> success
  5. retry exhaustion -> LLMUnavailable
  6. malformed JSON retried once then raises
  7. the API key never leaks into any exception message or stdout
  8. request shape: model/messages/temperature=0
"""

import hashlib
import json
import os
import socket
import urllib.error

import pytest

import axiom.llm as llm_mod
from axiom.llm import LLMClient, LLMUnavailable

FAKE_KEY = "sk-or-v1-SUPERSECRET-KEY-abcdef123456"
FAKE_KEY_MINIMAX = "eyJhbGciOiJIUzI1NiJ9-MINIMAXSECRET999"

ALL_KEYS = (FAKE_KEY, FAKE_KEY_MINIMAX)


# ---------------------------------------------------------------- fixtures --

@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Every test starts with a clean, key-free environment and never reads
    the developer's real repo-root `.env`."""
    for var in ("OPENROUTER_API_KEY", "MINIMAX_API_KEY",
                "OPENROUTER_MODEL", "MINIMAX_MODEL"):
        monkeypatch.delenv(var, raising=False)
    # Point the loader at a file that does not exist instead of stubbing
    # `_load_env` itself, so the loader's own tests still exercise real code.
    monkeypatch.setattr(llm_mod, "_env_path", lambda: tmp_path / "no-such.env")
    # Never sleep for real.
    monkeypatch.setattr(llm_mod, "_sleep", lambda _s: None)
    yield


class FakeResponse:
    """Minimal stand-in for what urlopen returns as a context manager."""

    def __init__(self, payload: bytes):
        self._body = payload

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def completion_text(content: str) -> bytes:
    """Encode a fake OpenAI-compatible chat completion body."""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }).encode("utf-8")


class FakeHTTP:
    """Records every call; replays a scripted list of responses/exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload,
                           "headers": headers, "timeout": timeout})
        if not self.script:
            raise AssertionError("network called more times than scripted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    @property
    def n_calls(self):
        return len(self.calls)


def install(monkeypatch, script):
    fake = FakeHTTP(script)
    monkeypatch.setattr(llm_mod, "_http_post", fake)
    return fake


def http_error(code, body=b"upstream said no"):
    return urllib.error.HTTPError(
        url="https://example.invalid/api",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,
        fp=None,
    )


def make_client(monkeypatch, tmp_path, provider="openrouter", model="test-model",
                script=None):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MINIMAX_API_KEY", FAKE_KEY_MINIMAX)
    client = LLMClient(provider=provider, model=model,
                       cache_dir=str(tmp_path / "cache"))
    fake = install(monkeypatch, script or [])
    return client, fake


# ------------------------------------------- 1. provider resolution / ctor --

def test_provider_from_openrouter_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    c = LLMClient(cache_dir=str(tmp_path))
    assert c.provider_name == "openrouter"
    assert c.endpoint == "https://openrouter.ai/api/v1/chat/completions"
    assert c.model == os.environ.get("OPENROUTER_MODEL", c.model)


def test_provider_falls_back_to_minimax(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", FAKE_KEY_MINIMAX)
    c = LLMClient(cache_dir=str(tmp_path))
    assert c.provider_name == "minimax"
    assert c.endpoint == "https://api.minimax.io/v1/chat/completions"


def test_openrouter_takes_precedence_over_minimax(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MINIMAX_API_KEY", FAKE_KEY_MINIMAX)
    assert LLMClient(cache_dir=str(tmp_path)).provider_name == "openrouter"


def test_explicit_provider_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MINIMAX_API_KEY", FAKE_KEY_MINIMAX)
    c = LLMClient(provider="minimax", cache_dir=str(tmp_path))
    assert c.provider_name == "minimax"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    with pytest.raises(LLMUnavailable):
        LLMClient(provider="anthropic", cache_dir=str(tmp_path))


def test_no_key_raises_at_construction(monkeypatch, tmp_path):
    with pytest.raises(LLMUnavailable) as ei:
        LLMClient(cache_dir=str(tmp_path))
    assert "key" in str(ei.value).lower()
    for k in ALL_KEYS:
        assert k not in str(ei.value)


# ------------------------------------------------------- 8. request shape --

def test_request_shape_is_openai_compatible(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[completion_text('{"a": 1}')])
    client.json("sys", "usr")
    call = fake.calls[0]
    assert fake.n_calls == 1
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    body = call["payload"]
    assert body["model"] == "test-model"
    assert body["temperature"] == 0
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert call["headers"]["Content-Type"] == "application/json"


# ------------------------------------------------------------- 2. the cache --

def test_cache_miss_calls_network_and_writes_cache(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[completion_text('{"plan": 1}')])
    assert client.json("s", "u") == {"plan": 1}
    assert fake.n_calls == 1
    key = hashlib.sha256(b"openrouter" + b"test-model" + b"s" + b"u").hexdigest()
    # cache written under cache_dir/<key>.json
    assert (tmp_path / "cache" / f"{key}.json").exists()


def test_cache_hit_does_not_touch_network(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[completion_text('{"plan": 1}')])
    client.json("s", "u")
    assert fake.n_calls == 1
    # A fresh client (cold cache dir contents, empty script) must still serve.
    client2 = LLMClient(provider="openrouter", model="test-model",
                        cache_dir=str(tmp_path / "cache"))
    install(monkeypatch, [])  # any network call would blow up
    assert client2.json("s", "u") == {"plan": 1}
    assert fake.n_calls == 1


def test_cache_key_includes_provider_model_system_user(monkeypatch, tmp_path):
    c1, _ = make_client(monkeypatch, tmp_path, script=[completion_text('{"v": 1}')])
    c1.json("s", "u")
    # different user -> miss -> would need a network call
    c2, fake = make_client(monkeypatch, tmp_path, script=[completion_text('{"v": 2}')])
    assert c2.json("s", "u2") == {"v": 2}
    assert fake.n_calls == 1

    c3, fake3 = make_client(monkeypatch, tmp_path, model="other-model",
                            script=[completion_text('{"v": 3}')])
    assert c3.json("s", "u") == {"v": 3}
    assert fake3.n_calls == 1

    c4, fake4 = make_client(monkeypatch, tmp_path, provider="minimax",
                            script=[completion_text('{"v": 4}')])
    assert c4.json("s", "u") == {"v": 4}
    assert fake4.n_calls == 1


def test_cache_dir_created_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    target = tmp_path / "deep" / "nested" / "cache"
    assert not target.exists()
    client = LLMClient(cache_dir=str(target))
    install(monkeypatch, [completion_text('{"ok": 1}')])
    client.json("s", "u")
    assert target.is_dir()


def test_corrupt_cache_entry_falls_back_to_network(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[completion_text('{"a": 1}')])
    client.json("s", "u")
    key = hashlib.sha256(b"openrouter" + b"test-model" + b"s" + b"u").hexdigest()
    (tmp_path / "cache" / f"{key}.json").write_text("{not json", encoding="utf-8")
    client2, fake2 = make_client(monkeypatch, tmp_path,
                                 script=[completion_text('{"a": 2}')])
    assert client2.json("s", "u") == {"a": 2}
    assert fake2.n_calls == 1


# ------------------------------------------------------- 3. fence stripping --

def test_markdown_fences_are_stripped(monkeypatch, tmp_path):
    fenced = "```json\n{\"fenced\": true}\n```"
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[completion_text(fenced)])
    assert client.json("s", "u") == {"fenced": True}
    assert fake.n_calls == 1


def test_bare_fence_without_language_tag_is_stripped(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[completion_text('```\n{"x": 2}\n```')])
    assert client.json("s", "u") == {"x": 2}


def test_prose_around_json_is_recovered(monkeypatch, tmp_path):
    chatty = 'Sure! Here is the plan:\n{"steps": ["a"]}\nHope that helps.'
    client, _ = make_client(monkeypatch, tmp_path, script=[completion_text(chatty)])
    assert client.json("s", "u") == {"steps": ["a"]}


# ----------------------------------------------------------- 4/5. retries --

def test_retry_on_429_then_success(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[
        http_error(429),
        http_error(429),
        completion_text('{"ok": "after retries"}'),
    ])
    assert client.json("s", "u") == {"ok": "after retries"}
    assert fake.n_calls == 3


def test_retry_on_500_then_success(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[
        http_error(503),
        completion_text('{"ok": true}'),
    ])
    assert client.json("s", "u") == {"ok": True}
    assert fake.n_calls == 2


def test_retry_on_timeout_then_success(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[
        socket.timeout("timed out"),
        urllib.error.URLError("connection reset"),
        completion_text('{"ok": 1}'),
    ])
    assert client.json("s", "u") == {"ok": 1}
    assert fake.n_calls == 3


def test_backoff_is_exponential_1_2_4(monkeypatch, tmp_path):
    slept = []
    monkeypatch.setattr(llm_mod, "_sleep", slept.append)
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[http_error(500), http_error(500),
                                    http_error(500)])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    assert slept == [1, 2, 4]


def test_exhaustion_raises_llm_unavailable(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path,
                               script=[http_error(429), http_error(429),
                                       http_error(429)])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    assert fake.n_calls == 3  # exactly 3 attempts, not 4


def test_no_sleep_when_first_attempt_succeeds(monkeypatch, tmp_path):
    slept = []
    monkeypatch.setattr(llm_mod, "_sleep", slept.append)
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[completion_text('{"a": 1}')])
    client.json("s", "u")
    assert slept == []


def test_401_is_not_retried(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[http_error(401)])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    assert fake.n_calls == 1


def test_failed_call_is_not_cached(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, script=[http_error(500)] * 3)
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    c2, fake2 = make_client(monkeypatch, tmp_path,
                            script=[completion_text('{"fresh": 1}')])
    assert c2.json("s", "u") == {"fresh": 1}
    assert fake2.n_calls == 1


# ------------------------------------------- 6. malformed JSON -> 1 retry --

def test_malformed_json_retried_once_with_stricter_prompt(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[
        completion_text("not json at all"),
        completion_text('{"recovered": true}'),
    ])
    assert client.json("sys", "usr") == {"recovered": True}
    assert fake.n_calls == 2
    second = fake.calls[1]["payload"]["messages"]
    assert second[1]["content"].startswith("usr")   # original user text kept
    assert len(second[1]["content"]) > len("usr")   # strict suffix appended


def test_malformed_json_twice_raises(monkeypatch, tmp_path):
    client, fake = make_client(monkeypatch, tmp_path, script=[
        completion_text("<html>oops</html>"),
        completion_text("still not json"),
    ])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    assert fake.n_calls == 2  # one strict retry, no more


def test_json_repair_retry_is_not_cached_on_failure(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[completion_text("nope"),
                                    completion_text("nope")])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")
    c2, fake2 = make_client(monkeypatch, tmp_path,
                            script=[completion_text('{"ok": 1}')])
    assert c2.json("s", "u") == {"ok": 1}
    assert fake2.n_calls == 1


def test_non_dict_json_is_rejected(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[completion_text("[1, 2, 3]"),
                                    completion_text("[1, 2, 3]")])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")


def test_missing_choices_key_raises(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[json.dumps({"error": "nope"}).encode()])
    with pytest.raises(LLMUnavailable):
        client.json("s", "u")


# --------------------------------------------------- 7. THE KEY LEAK TESTS --

def _assert_no_leak(text):
    for k in ALL_KEYS:
        assert k not in text, f"API KEY LEAKED into: {text!r}"


def test_key_never_leaks_on_construction_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    with pytest.raises(LLMUnavailable) as ei:
        LLMClient(provider="nonexistent-provider", cache_dir=str(tmp_path))
    _assert_no_leak(str(ei.value))
    out = capsys.readouterr()
    _assert_no_leak(out.out)
    _assert_no_leak(out.err)


def test_key_never_leaks_on_every_http_failure_path(monkeypatch, tmp_path, capsys):
    """Walk every failure path; the key must appear in no message and no stdout."""
    failure_scripts = {
        "exhausted_429": [http_error(429)] * 3,
        "exhausted_500": [http_error(500)] * 3,
        "timeout": [socket.timeout("t"), socket.timeout("t"), socket.timeout("t")],
        "urlerror": [urllib.error.URLError("dns")] * 3,
        "auth_401": [http_error(401)],
        "auth_403": [http_error(403)],
        "bad_envelope": [json.dumps({"error": "no choices here"}).encode()],
        "malformed_json": [completion_text("nope")] * 2,
        "empty_body": [b""],
    }
    for label, script in failure_scripts.items():
        client, fake = make_client(monkeypatch, tmp_path / label, script=script)
        with pytest.raises(LLMUnavailable) as ei:
            client.json("system prompt", "user prompt")
        _assert_no_leak(str(ei.value) + repr(ei.value))
        out = capsys.readouterr()
        _assert_no_leak(out.out)
        _assert_no_leak(out.err)


def test_key_never_leaks_when_key_appears_in_upstream_body(monkeypatch, tmp_path,
                                                          capsys):
    """Even if the upstream echoes the key back, it must not reach the message."""
    body = json.dumps({"error": {"message": f"invalid key {FAKE_KEY}"}}).encode()
    err = urllib.error.HTTPError(url="u", code=400, msg="bad", hdrs=None,
                                 fp=io_bytesio(body))
    client, _ = make_client(monkeypatch, tmp_path, script=[err])
    with pytest.raises(LLMUnavailable) as ei:
        client.json("s", "u")
    _assert_no_leak(str(ei.value))
    _assert_no_leak(capsys.readouterr().out)


def test_key_not_written_to_disk_by_cache(monkeypatch, tmp_path, capsys):
    client, _ = make_client(monkeypatch, tmp_path,
                            script=[completion_text('{"a": 1}')])
    client.json("s", "u")
    for p in (tmp_path / "cache").rglob("*"):
        if p.is_file():
            _assert_no_leak(p.read_text(encoding="utf-8"))
    _assert_no_leak(capsys.readouterr().out)


def test_repr_and_module_do_not_expose_key(monkeypatch, tmp_path):
    """The key lives in memory (it must, to sign requests) but must never be
    reachable through anything the app prints, logs or raises."""
    client, _ = make_client(monkeypatch, tmp_path)
    _assert_no_leak(repr(client))
    _assert_no_leak(str(client.endpoint))
    _assert_no_leak(str(client.model))
    _assert_no_leak(str(client.provider_name))
    for name in dir(llm_mod):
        obj = getattr(llm_mod, name)
        if isinstance(obj, str):
            _assert_no_leak(obj)


def io_bytesio(data):
    import io
    return io.BytesIO(data)


# -------------------------------------------------------- 9. .env handling --

def test_env_file_loaded_when_dotenv_missing(monkeypatch, tmp_path):
    """Fallback parser reads KEY=VALUE pairs from repo-root .env."""
    monkeypatch.setattr(llm_mod, "_DOTENV_AVAILABLE", False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nOPENROUTER_API_KEY=from-file\nQUOTED=\"q\"\n\n"
        "export MINIMAX_API_KEY=mini\nBROKEN LINE\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_mod, "_env_path", lambda: env_file)
    for var in ("OPENROUTER_API_KEY", "MINIMAX_API_KEY", "QUOTED", "BROKEN"):
        monkeypatch.delenv(var, raising=False)
    llm_mod._load_env()
    assert os.environ["OPENROUTER_API_KEY"] == "from-file"
    assert os.environ["QUOTED"] == "q"
    assert os.environ["MINIMAX_API_KEY"] == "mini"


def test_dotenv_used_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_mod, "_DOTENV_AVAILABLE", True)
    calls = []
    monkeypatch.setattr(llm_mod, "_dotenv_load", lambda p: calls.append(p))
    llm_mod._load_env()
    assert len(calls) == 1
    assert str(calls[0]).endswith(".env")


def test_load_env_does_not_overwrite_existing_env(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_mod, "_DOTENV_AVAILABLE", False)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr(llm_mod, "_env_path", lambda: env_file)
    monkeypatch.setenv("OPENROUTER_API_KEY", "already-set")
    llm_mod._load_env()
    assert os.environ["OPENROUTER_API_KEY"] == "already-set"


def test_model_env_var_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("OPENROUTER_MODEL", "some/free-model")
    c = LLMClient(cache_dir=str(tmp_path))
    assert c.model == "some/free-model"


def test_explicit_model_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setenv("OPENROUTER_MODEL", "env-model")
    c = LLMClient(model="explicit-model", cache_dir=str(tmp_path))
    assert c.model == "explicit-model"


def test_health_style_probe_never_raises(monkeypatch, tmp_path):
    """`provider_name` style probing used by /api/health must not explode."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr(llm_mod, "_load_env", lambda: None)
    with pytest.raises(LLMUnavailable):
        LLMClient(cache_dir=str(tmp_path))