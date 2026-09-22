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
    max_tokens: int = 700
    timeout_s: float = 45.0

class STTConfig(BaseModel):
    model_id: str
    timeout_s: float = 60.0

class TTSConfig(BaseModel):
    enabled: bool = True
    model_id: str = "canopylabs/orpheus-v1-english"
    voice: str = "autumn"
    max_chars: int = 200
    timeout_s: float = 45.0
    # Сколько подряд ошибок переводит TTS в паузу и на сколько секунд
    failure_threshold: int = 3
    cooldown_s: float = 300.0
    # Замедление для кнопки «медленнее»; ffmpeg atempo принимает 0.5-2.0
    slow_tempo: float = 0.75
    # Telegram file_id переиспользуется вместо повторного синтеза
    cache_ttl_s: int = 2592000

class DialogConfig(BaseModel):
    """Ролевой голосовой диалог."""

    enabled: bool = True
    max_turns: int = 8
    max_duration_s: int = 1800
    hints_count: int = 3
    # Длина реплики роли: диалог должен оставаться быстрым
    max_reply_chars: int = 160

class BotConfig(BaseModel):
    max_history_len: int = 12
    use_redis: bool = True
    session_ttl_s: int = 172800
    max_voice_duration_s: int = 180
    max_voice_size_bytes: int = 20 * 1024 * 1024
    # Минимальный интервал между запросами одного пользователя
    min_request_interval_s: float = 1.0
    redis_retry_interval_s: float = 30.0

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
    tts: TTSConfig = Field(default_factory=TTSConfig)
    dialog: DialogConfig = Field(default_factory=DialogConfig)
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
