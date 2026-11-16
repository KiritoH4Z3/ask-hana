# Silent failures this file catches:
# - an explicit provider that cannot work quietly degrading to another mode (the page would
#   claim Claude while serving extractive answers)
# - a bad number in .env being coerced or ignored instead of refusing to start
# - the API key leaking through repr() into a log line
from __future__ import annotations

import pytest

from ask_hana.config import Settings, load_settings, ollama_has_model, resolve_provider
from ask_hana.errors import ConfigError


def never(url, model):
    raise AssertionError("Ollama must not be probed here")


def test_defaults_match_the_contract():
    s = load_settings({})
    assert (s.provider, s.claude_model, s.claude_effort) == ("auto", "claude-opus-5-5", "low")
    assert (s.top_k, s.min_score, s.rate_limit_per_minute) == (4, 0.33, 12)
    assert (s.provider_timeout_s, s.host, s.port) == (60.0, "127.0.0.1", 3012)
    assert str(s.knowledge_dir) == "knowledge" and str(s.chroma_path) == "data/chroma"
    assert s.anthropic_api_key is None and s.ollama_model is None


def test_blank_values_count_as_unset():
    s = load_settings({"ANTHROPIC_API_KEY": "  ", "OLLAMA_MODEL": "", "TOP_K": ""})
    assert s.anthropic_api_key is None and s.ollama_model is None and s.top_k == 4


def test_overrides_are_read():
    s = load_settings(
        {
            "TOP_K": "6",
            "MIN_SCORE": "0.5",
            "PORT": "4000",
            "OLLAMA_URL": "http://h:1/",
            "CLAUDE_EFFORT": "HIGH",
        }
    )
    assert (s.top_k, s.min_score, s.port, s.ollama_url, s.claude_effort) == (
        6,
        0.5,
        4000,
        "http://h:1",
        "high",
    )


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({"ASK_HANA_PROVIDER": "gpt"}, "ASK_HANA_PROVIDER"),
        ({"CLAUDE_EFFORT": "max"}, "CLAUDE_EFFORT"),
        ({"TOP_K": "0"}, "TOP_K"),
        ({"TOP_K": "9"}, "TOP_K"),
        ({"TOP_K": "four"}, "TOP_K"),
        ({"MIN_SCORE": "1.5"}, "MIN_SCORE"),
        ({"PORT": "70000"}, "PORT"),
        ({"PROVIDER_TIMEOUT_S": "0"}, "PROVIDER_TIMEOUT_S"),
    ],
)
def test_bad_values_refuse_with_the_variable_name(env, needle):
    with pytest.raises(ConfigError) as err:
        load_settings(env)
    assert needle in str(err.value)


def test_repr_hides_the_key():
    assert "sk-ant-secret" not in repr(Settings(anthropic_api_key="sk-ant-secret"))


def test_explicit_claude_without_key_refuses():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        resolve_provider(Settings(provider="claude"), never)


def test_explicit_claude_with_key():
    r = resolve_provider(Settings(provider="claude", anthropic_api_key="k"), never)
    assert (r.mode, r.model) == ("claude", "claude-opus-5-5")


def test_explicit_ollama_without_model_refuses_and_names_the_fix():
    with pytest.raises(ConfigError, match="OLLAMA_MODEL"):
        resolve_provider(Settings(provider="ollama"), never)


def test_explicit_ollama_is_not_probed():
    r = resolve_provider(Settings(provider="ollama", ollama_model="m:1"), never)
    assert (r.mode, r.model) == ("ollama", "m:1")


def test_explicit_extractive():
    r = resolve_provider(Settings(provider="extractive", anthropic_api_key="k"), never)
    assert (r.mode, r.model) == ("extractive", None)


def test_auto_prefers_claude_when_key_set():
    r = resolve_provider(Settings(anthropic_api_key="k", ollama_model="m"), never)
    assert r.mode == "claude" and "ANTHROPIC_API_KEY" in r.reason


def test_auto_uses_ollama_when_model_is_installed():
    seen = []
    r = resolve_provider(
        Settings(ollama_model="qwen3.5:9b"), lambda url, model: seen.append((url, model)) or True
    )
    assert (r.mode, r.model) == ("ollama", "qwen3.5:9b")
    assert seen == [("http://127.0.0.1:11434", "qwen3.5:9b")]


def test_auto_falls_back_to_extractive_when_model_not_installed():
    r = resolve_provider(Settings(ollama_model="ghost"), lambda u, m: False)
    assert r.mode == "extractive" and "ghost" in r.reason


def test_auto_without_any_config_is_extractive_and_never_probes():
    r = resolve_provider(Settings(), never)
    assert r.mode == "extractive" and "OLLAMA_MODEL" in r.reason


def test_probe_reads_tags(monkeypatch):
    import httpx

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3.5:9b"}, {"name": "tiny:latest"}]}

    monkeypatch.setattr(httpx, "get", lambda url, timeout: R())
    assert ollama_has_model("http://x", "qwen3.5:9b")
    assert ollama_has_model("http://x", "tiny")
    assert not ollama_has_model("http://x", "other")


def test_probe_failure_means_false(monkeypatch):
    import httpx

    def boom(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", boom)
    assert ollama_has_model("http://x", "m") is False
