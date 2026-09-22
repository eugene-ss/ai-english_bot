import os

from src.util.paths import PROJECT_ROOT
from src.util.yaml import load_yaml

ICONS = load_yaml(os.path.join(PROJECT_ROOT, "images", "icons.yaml"))
STRINGS = load_yaml(os.path.join(PROJECT_ROOT, "locales", "ru.yaml"))

def t(key: str, **kwargs) -> str:
    text = STRINGS[key]
    for name, value in kwargs.items():
        text = text.replace("{" + name + "}", str(value))
    return text

def icon(key: str) -> str:
    return ICONS[key]

def labeled(icon_key: str, text_key: str, **kwargs) -> str:
    return f"{icon(icon_key)} {t(text_key, **kwargs)}"
