import json
import asyncio
import subprocess
import logging
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from groq import Groq
from google import genai
from google.genai import types
from src.config import settings

logger = logging.getLogger("eng_bot")

class AIProviderManager:
    def __init__(self):
        self.groq_client = Groq(api_key=settings.groq_api_key.get_secret_value())
        self.gemini_client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

        self.system_instruction = (
            "Ты — опытный, дружелюбный и терпеливый преподаватель английского языка для русскоязычных студентов. "
            "Общайся на английском языке (на 70-80%), пояснения правил пиши на РУССКОМ. "
            "В конце сообщения ВСЕГДА задавай ОДИН вопрос пользователю. Пиши кратко. "
            "Если пользователь ответил голосом, обрати внимание на построение фразы и похвали за Speaking."
        )

    def convert_ogg_to_wav(self, input_path: str, output_path: str):
        command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path
        ]
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    def transcribe_audio(self, wav_file_path: str) -> str:
        with open(wav_file_path, "rb") as file:
            transcription = self.groq_client.audio.transcriptions.create(
                file=(wav_file_path, file.read()),
                model=settings.stt.model_id,
                response_format="text"
            )
        return transcription

    async def get_text_response(self, history_messages: list) -> str:
        provider = settings.llm.active_text_provider
        if provider == "gemini":
            return await self._call_gemini(history_messages)
        elif provider == "groq":
            return await self._call_groq(history_messages)
        raise ValueError(f"Unknown provider: {provider}")

    async def _call_gemini(self, history: list) -> str:
        formatted_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            formatted_history.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg["text"])])
            )
        cfg = settings.llm.gemini
        response = await self.gemini_client.aio.models.generate_content(
            model=cfg.model_id,
            contents=formatted_history,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=cfg.temperature
            )
        )
        return response.text

    async def _call_groq(self, history: list) -> str:
        cfg = settings.llm.groq
        # Подготовка сообщений для Groq OpenAI формата
        messages = [{"role": "system", "content": self.system_instruction}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["text"]})

        loop = asyncio.get_running_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: self.groq_client.chat.completions.create(
                model=cfg.model_id,
                messages=messages,
                temperature=cfg.temperature
            )
        )
        return completion.choices[0].message.content

class DurableStorage:
    def __init__(self):
        self.use_redis = settings.bot.use_redis
        self.local_storage = {}
        self.redis = None

        if self.use_redis:
            try:
                self.redis = Redis.from_url(
                    settings.redis_url.get_secret_value(),
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                self.redis.ping()
                logger.info("Successfully connected to Redis instance.")
            except (RedisConnectionError, Exception) as e:
                logger.warning(
                    f"Redis connection failed ({e}). "
                    f"Falling back to volatile In-Memory history storage."
                )
                self.use_redis = False

    def get_history(self, user_id: int) -> list:
        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                data = self.redis.get(key)
                return json.loads(data) if data else []
            except Exception as e:
                logger.error(f"Redis GET failed for user {user_id}, running memory fallback: {e}")
                return self.local_storage.get(user_id, [])
        else:
            return self.local_storage.get(user_id, [])

    def add(self, user_id: int, role: str, text: str):
        history = self.get_history(user_id)
        history.append({"role": role, "text": text})

        if len(history) > settings.bot.max_history_len:
            history = history[-settings.bot.max_history_len:]

        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                self.redis.set(key, json.dumps(history), ex=172800)
                return
            except Exception as e:
                logger.error(f"Redis SET failed for user {user_id}, running memory fallback: {e}")

        self.local_storage[user_id] = history

    def clear(self, user_id: int):
        if self.use_redis:
            try:
                key = f"chat_session:{user_id}"
                self.redis.delete(key)
                return
            except Exception as e:
                logger.error(f"Redis DELETE failed for user {user_id}: {e}")

        if user_id in self.local_storage:
            self.local_storage[user_id] = []

ai = AIProviderManager()
sessions = DurableStorage()