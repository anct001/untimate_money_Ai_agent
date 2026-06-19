"""Configuration loading.

Defaults live here so the project runs out of the box. A `config/config.yaml`
(optional) deep-merges over these defaults, and API keys come from the
environment / `.env`.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a core dep
    yaml = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional at runtime
    load_dotenv = None


DEFAULT_CONFIG: dict[str, Any] = {
    "providers": [
        {
            "name": "ollama",
            "type": "ollama",
            "enabled": True,
            "tiers": ["light"],
            "models": {"light": "llama3.2:3b", "heavy": "llama3.1:8b"},
            "daily_request_limit": 0,
        },
        {
            "name": "groq",
            "type": "openai_compat",
            "enabled": True,
            "tiers": ["light", "heavy"],
            "base_url": "https://api.groq.com/openai/v1",
            "api_key_env": "GROQ_API_KEY",
            "models": {
                "light": "llama-3.1-8b-instant",
                "heavy": "llama-3.3-70b-versatile",
            },
            "daily_request_limit": 1000,
        },
        {
            "name": "gemini",
            "type": "gemini",
            "enabled": True,
            "tiers": ["light", "heavy"],
            "api_key_env": "GEMINI_API_KEY",
            "models": {
                "light": "gemini-2.0-flash-lite",
                "heavy": "gemini-2.0-flash",
            },
            "daily_request_limit": 1500,
        },
        {
            "name": "openrouter",
            "type": "openai_compat",
            "enabled": True,
            "tiers": ["heavy"],
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "models": {"heavy": "meta-llama/llama-3.3-70b-instruct:free"},
            "daily_request_limit": 50,
        },
        {
            "name": "cerebras",
            "type": "openai_compat",
            "enabled": True,
            "tiers": ["light", "heavy"],
            "base_url": "https://api.cerebras.ai/v1",
            "api_key_env": "CEREBRAS_API_KEY",
            "models": {"light": "llama3.1-8b", "heavy": "llama-3.3-70b"},
            "daily_request_limit": 1000,
        },
        {
            "name": "together",
            "type": "openai_compat",
            "enabled": True,
            "tiers": ["heavy"],
            "base_url": "https://api.together.xyz/v1",
            "api_key_env": "TOGETHER_API_KEY",
            "models": {"heavy": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"},
            "daily_request_limit": 100,
        },
    ],
    "paths": {"data_dir": "data", "output_dir": "outputs"},
    "goal": {"monthly_target_usd": 10000},
    "router": {
        "max_retries": 2,
        "cooldown_seconds": 30,
        "daily_budget_usd": 0,   # 0 = no cap; raise this only if using paid models
        "cache": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Config:
    providers: list[dict] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    goal: dict[str, Any] = field(default_factory=dict)
    router: dict[str, Any] = field(default_factory=dict)
    root: Path = field(default_factory=Path.cwd)

    @property
    def data_dir(self) -> Path:
        return self.root / self.paths.get("data_dir", "data")

    @property
    def output_dir(self) -> Path:
        return self.root / self.paths.get("output_dir", "outputs")

    @property
    def monthly_target_usd(self) -> float:
        return float(self.goal.get("monthly_target_usd", 10000))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_config(path: str | os.PathLike | None = None, root: str | os.PathLike | None = None) -> Config:
    """Load config: defaults <- config.yaml <- (env keys resolved at provider build time)."""
    root_path = Path(root or os.getcwd())

    if load_dotenv is not None:
        load_dotenv(root_path / ".env")

    merged = copy.deepcopy(DEFAULT_CONFIG)

    config_path = Path(path) if path else root_path / "config" / "config.yaml"
    if config_path.exists():
        if yaml is None:
            raise RuntimeError("PyYAML is required to read config.yaml. pip install PyYAML")
        with open(config_path, encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
        merged = _deep_merge(merged, user_cfg)

    return Config(
        providers=merged.get("providers", []),
        paths=merged.get("paths", {}),
        goal=merged.get("goal", {}),
        router=merged.get("router", {}),
        root=root_path,
    )
