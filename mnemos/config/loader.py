"""
Configuration loader for Mnemos.

Loads configuration from three sources with increasing priority:
1. Default values (from defaults.py)
2. JSON config file (if it exists)
3. Environment variables (MNEMOS_ prefix)

Environment variable mapping:
    MNEMOS_STORE_DB_PATH -> config["store"]["db_path"]
    MNEMOS_CONSOLIDATION_DECAY_RATE -> config["consolidation"]["decay_rate"]
    etc.

The loader performs deep merging: JSON config values override defaults,
and environment variables override JSON config values.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..file_security import atomic_write_text, secure_directory

from .defaults import DEFAULT_CONFIG


def load_config(
    config_path: str | Path | None = None,
    env_prefix: str | None = "MNEMOS_",
) -> dict[str, Any]:
    """Load Mnemos configuration from defaults, JSON file, and env vars.

    Priority (highest wins):
    1. Environment variables (MNEMOS_ prefix)
    2. JSON config file
    3. Default values

    Args:
        config_path: Path to a JSON configuration file. If None, looks for
            ~/.mnemos/config.json. If that doesn't exist, uses defaults only.
        env_prefix: Prefix for environment variable overrides. None reads
            the file alone, with no override from the environment.

    Returns:
        Merged configuration dictionary.

    Raises:
        json.JSONDecodeError: If the config file contains invalid JSON.
    """
    config = deepcopy(DEFAULT_CONFIG)

    # Load JSON config file
    if config_path is None:
        config_path = Path.home() / ".mnemos" / "config.json"
    else:
        config_path = Path(config_path)

    if config_path.exists():
        with open(config_path) as f:
            file_config = json.load(f)
        config = _deep_merge(config, file_config)

    # Apply environment variable overrides
    if env_prefix is not None:
        config = _apply_env_overrides(config, env_prefix)

    return config


def save_config(config: dict, config_path: str | Path | None = None) -> None:
    """Save configuration to JSON file.

    Args:
        config: Configuration dictionary to save.
        config_path: Path to write. Defaults to ~/.mnemos/config.json.
    """
    if config_path is None:
        config_path = Path.home() / ".mnemos" / "config.json"
    else:
        config_path = Path(config_path)

    private_root = Path.home() / ".mnemos"
    secure_directory(config_path.parent, force=config_path.parent == private_root)

    # Convert tuples to lists for JSON serialization
    def _prep(obj):
        if isinstance(obj, dict):
            return {k: _prep(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_prep(v) for v in obj]
        return obj

    atomic_write_text(config_path, json.dumps(_prep(config), indent=2) + "\n")


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, returning a new dict.

    Args:
        base: The base dictionary (not modified).
        override: Values to overlay on top of base.

    Returns:
        New dictionary with merged values.
    """
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _apply_env_overrides(config: dict, prefix: str) -> dict:
    """Apply environment variable overrides to config.

    Maps MNEMOS_SECTION_KEY=value to config["section"]["key"] = value.
    Attempts type coercion: bool, int, float, then string.

    Args:
        config: The configuration dict to apply overrides to (modified in place).
        prefix: The environment variable prefix to scan for.

    Returns:
        The modified config dict.
    """
    for key, value in _named_overrides(config, prefix):
        if not key.startswith(prefix):
            continue
        # MNEMOS_STORE_DB_PATH -> ["store", "db_path"]
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) == 1:
            # Top-level key (e.g., MNEMOS_AGENT_ID -> config["agent_id"])
            config[parts[0]] = _coerce_type(value)
        elif len(parts) == 2:
            section, subkey = parts
            if section not in config:
                config[section] = {}
            if isinstance(config[section], dict):
                config[section][subkey] = _coerce_type(value)
    return config


def _named_overrides(config: dict, prefix: str) -> list[tuple[str, str]]:
    """The names and values that override the file: this process's
    environment. Inside a host that hands the settings out (Hermes) they are
    asked of the host instead, which answers for the profile that is speaking:
    one gateway serves several, and its own environment is the one it was
    started for, so a number set there was every profile's. A host answers
    for a name and gives no list, so each name the config has is asked for."""
    from ..llm import _find_env_key, host_secrets_active

    if not host_secrets_active():
        return list(os.environ.items())
    names: list[str] = []
    for section, value in config.items():
        if isinstance(value, dict):
            names.extend(f"{prefix}{section}_{key}".upper() for key in value)
        elif "_" not in section:
            names.append(f"{prefix}{section}".upper())
    return [(name, found) for name in names if (found := _find_env_key(name)[0])]


def _coerce_type(value: str) -> Any:
    """Attempt to coerce a string value to bool, int, float, or leave as string."""
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
