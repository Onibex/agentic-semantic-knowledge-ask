# SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
# Copyright (c) 2026 Onibex, LLC. All rights reserved.
#
# Part of Onibex ASK — Agentic Semantic Knowledge.
# Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
# Commercial licenses: contact@onibex.com — see LICENSE.

"""
ConfigManager — plain read/write access to `config/settings.json`.

No UI dependency: usable from any non-UI layer. OpenSearch connection
settings are resolved env-first (`OPENSEARCH_*`), not from this file.
"""
import json
from pathlib import Path
from typing import Dict, Optional


class ConfigManager:
    """Manages the system configuration file."""

    def __init__(self, config_file: str = "config/settings.json"):
        self.config_file = Path(config_file)
        self.config_file.parent.mkdir(exist_ok=True)

    def save_config(self, config: Dict) -> bool:
        """Save the configuration to the JSON file."""
        try:
            with open(self.config_file, "w") as f:
                json.dump(config, f, indent=4)
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
            return False

    def load_config(self) -> Optional[Dict]:
        """Load the configuration from the JSON file."""
        if not self.config_file.exists():
            return None
        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ConfigManager] Error loading config: {e}")
            return None

    def config_exists(self) -> bool:
        return self.config_file.exists()

    def delete_config(self) -> bool:
        try:
            if self.config_file.exists():
                self.config_file.unlink()
            return True
        except Exception as e:
            print(f"[ConfigManager] Error deleting config: {e}")
            return False

    def get_db_type(self) -> str:
        config = self.load_config()
        if config:
            return config.get("db_type", "postgresql")
        return "postgresql"

    def validate_config(self, config: Dict) -> tuple:
        db_type = config.get("db_type", "postgresql")
        db_section = "hana" if db_type == "hana" else "postgresql"
        db_fields = (
            ["host", "port", "user", "password"]
            if db_type == "hana"
            else ["host", "port", "database", "user", "password"]
        )

        required_fields = {
            db_section: db_fields,
            "opensearch": ["host", "port"],
            "sap_ai_core": ["config_path"],
            "deployments": ["llm", "embeddings"],
        }

        for section, fields in required_fields.items():
            if section not in config:
                return False, f"Missing section '{section}'"
            for field in fields:
                if field not in config[section] or not config[section][field]:
                    return False, f"Missing field '{field}' in section '{section}'"

        return True, "Valid configuration"
