"""Offline tests for config, cache and memory."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moneyagent.cache import PromptCache  # noqa: E402
from moneyagent.config import _deep_merge, load_config  # noqa: E402
from moneyagent.memory import Memory  # noqa: E402


def test_deep_merge_nested():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 20, "z": 30}, "c": 4}
    out = _deep_merge(base, override)
    assert out == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3, "c": 4}
    assert base["a"]["y"] == 2  # original untouched


def test_load_config_defaults(tmp_path):
    cfg = load_config(root=tmp_path)
    assert cfg.monthly_target_usd == 10000
    assert cfg.router["max_retries"] == 2
    assert any(p["name"] == "ollama" for p in cfg.providers)
    assert cfg.data_dir == tmp_path / "data"


def test_load_config_yaml_override(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        "goal:\n  monthly_target_usd: 5000\nrouter:\n  max_retries: 7\n",
        encoding="utf-8",
    )
    cfg = load_config(root=tmp_path)
    assert cfg.monthly_target_usd == 5000
    assert cfg.router["max_retries"] == 7
    # untouched defaults still present
    assert cfg.router["cache"] is True


def test_cache_set_get_and_disabled(tmp_path):
    cache = PromptCache(tmp_path / "c.json", enabled=True)
    key = cache.key([{"role": "user", "content": "hi"}], "light", 0.7, 100)
    assert cache.get(key) is None
    cache.set(key, "answer")
    assert cache.get(key) == "answer"

    disabled = PromptCache(tmp_path / "d.json", enabled=False)
    disabled.set(key, "x")
    assert disabled.get(key) is None


def test_cache_ttl_expiry(tmp_path):
    cache = PromptCache(tmp_path / "c.json", ttl_seconds=10, enabled=True)
    key = "k"
    cache.set(key, "v")
    cache._data[key]["ts"] = 0  # force stale
    assert cache.get(key) is None


def test_memory_roundtrip(tmp_path):
    mem = Memory(tmp_path / "m.jsonl")
    mem.add("note", "first", tag="a")
    mem.add("note", "second", tag="b")
    recent = mem.recent(10)
    assert len(recent) == 2
    assert recent[-1]["content"] == "second"
    assert recent[-1]["tag"] == "b"
