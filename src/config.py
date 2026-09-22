import os
from typing import Literal

from pydantic import BaseModel, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.util.paths import PROJECT_ROOT
from src.util.yaml import load_yaml

class ProviderConfig(BaseModel):
    model_id: str
    temperature: float = 0.7

class LLMConfig(BaseModel):
    active_text_provider: Literal["gemini", "groq"]
    gemini: ProviderConfig
    groq: ProviderConfig

class STTConfig(BaseModel):
    model_id: str

class BotConfig(BaseModel):
    max_history_len: int = 12
    use_redis: bool = True

class AppSettings(BaseSettings):
    telegram_bot_token: SecretStr = Field(..., alias="TELEGRAM_BOT_TOKEN")
    groq_api_key: SecretStr = Field(..., alias="GROQ_API_KEY")
    gemini_api_key: SecretStr = Field(..., alias="GEMINI_API_KEY")
    redis_url: SecretStr = Field(default=SecretStr("redis://redis:6379/0"), alias="REDIS_URL")

    loki_url: str = Field(default="", alias="LOKI_URL")
    loki_user: str = Field(default="", alias="LOKI_USER")
    loki_password: SecretStr = Field(default=SecretStr(""), alias="LOKI_PASSWORD")

    llm: LLMConfig
    stt: STTConfig
    bot: BotConfig

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

def load_config() -> AppSettings:
    config_path = os.getenv(
        "CONFIG_PATH",
        os.path.join(PROJECT_ROOT, "config", "app_config.yaml"),
    )
    yaml_data = load_yaml(config_path)
    return AppSettings(**yaml_data)

settings = load_config()