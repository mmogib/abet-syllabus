"""Configuration file support for the ABET Syllabus Generator.

Looks for configuration in:
1. Path specified by --config CLI flag
2. ./abet_syllabus.yaml (current directory)
3. ~/.abet_syllabus.yaml (home directory)

CLI flags always override config file values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "abet_syllabus.db"
_DEFAULT_TEMPLATE = "resources/templates/ABETSyllabusTemplate.docx"
_DEFAULT_OUTPUT_DIR = "./output"
_DEFAULT_AI_PROVIDER = "anthropic"
_DEFAULT_LOG_FILE = "abet_syllabus.log"
_DEFAULT_LOG_LEVEL = "INFO"

_CONFIG_FILENAMES = [
    "abet_syllabus.yaml",
    "abet_syllabus.yml",
]


@dataclass
class Config:
    """Application configuration."""

    db_path: str = _DEFAULT_DB_PATH
    template_path: str = _DEFAULT_TEMPLATE
    output_dir: str = _DEFAULT_OUTPUT_DIR
    ai_provider: str = _DEFAULT_AI_PROVIDER
    log_file: str = _DEFAULT_LOG_FILE
    log_level: str = _DEFAULT_LOG_LEVEL

    @classmethod
    def load(cls, config_path: str | None = None) -> "Config":
        """Load configuration from file, falling back to defaults.

        Search order:
        1. Explicit config_path argument
        2. ./abet_syllabus.yaml
        3. ~/.abet_syllabus.yaml

        Args:
            config_path: Explicit path to a YAML config file.

        Returns:
            Config instance with loaded or default values.
        """
        config = cls()

        # Find config file
        file_path = _find_config_file(config_path)
        if file_path is None:
            logger.debug("No config file found; using defaults")
            return config

        # Load YAML
        data = _load_yaml_file(file_path)
        if data is None:
            return config

        logger.debug("Loaded config from %s", file_path)

        # Apply values from file
        if isinstance(data, dict):
            if "db_path" in data and isinstance(data["db_path"], str):
                config.db_path = data["db_path"]
            if "template_path" in data and isinstance(data["template_path"], str):
                config.template_path = data["template_path"]
            if "output_dir" in data and isinstance(data["output_dir"], str):
                config.output_dir = data["output_dir"]
            if "ai_provider" in data and isinstance(data["ai_provider"], str):
                config.ai_provider = data["ai_provider"]
            if "log_file" in data and isinstance(data["log_file"], str):
                config.log_file = data["log_file"]
            if "log_level" in data and isinstance(data["log_level"], str):
                config.log_level = data["log_level"]

        return config

    def apply_cli_overrides(self, **kwargs: str | None) -> None:
        """Apply CLI flag overrides (non-None values replace config values).

        Args:
            **kwargs: Keyword arguments matching Config field names.
                Only non-None values will override the current config.
        """
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key):
                setattr(self, key, value)


def _find_config_file(explicit_path: str | None = None) -> Path | None:
    """Locate the configuration file.

    Args:
        explicit_path: If provided, use this path directly.

    Returns:
        Path to the config file, or None if not found.
    """
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        logger.warning("Specified config file not found: %s", explicit_path)
        return None

    # Search in current directory
    for name in _CONFIG_FILENAMES:
        p = Path.cwd() / name
        if p.exists():
            return p

    # Search in home directory
    for name in _CONFIG_FILENAMES:
        p = Path.home() / f".{name}"
        if p.exists():
            return p

    return None


def _load_yaml_file(path: Path) -> dict | None:
    """Load and parse a YAML file safely.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed dict or None on error.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; cannot read config file")
        return None

    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Failed to parse config file %s: %s", path, exc)
        return None
