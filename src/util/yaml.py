from typing import Any

import yaml


def load_yaml(path: str) -> Any:
    """Читает YAML. Корнем может быть и словарь, и список (сценарии)."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
