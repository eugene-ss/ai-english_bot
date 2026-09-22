import asyncio

from groq import Groq
from google import genai
from google.genai import types

from src.config import settings

class AIProviderManager:
    def __init__(self):
        self.groq_client = Groq(api_key=settings.groq_api_key.get_secret_value())
        self.gemini_client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

        self.system_instruction = (
            "Ты — опытный, дружелюбный и терпеливый преподаватель английского языка для русскоязычных студентов (уровень A1, с нуля). "
            "Общайся на английском языке (на 70-80%), пояснения правил пиши на РУССКОМ. "
            "Твоя цель: научить ученика реально использовать английский в коротких диалогах. "
            "Язык: "
            "- Объяснения на русском, коротко. "
            "- Примеры, исправления и упражнения - на английском. "
            "ОБЯЗАТЕЛЬНОЕ СТРОГОЕ ПРАВИЛО: "
            "Отвечай коротко и структурно: максимум 5-10 строк. "
            "Ошибки: перечисли ключевые ошибки (если имеются) - самые важные. "
            "исправленный вариант (английский) - 1 строка. "
            "ОГРАНИЧЕНИЯ: "
            "- Не вводи новую сложную грамматику и лексику сверх A1. "
            "- Если пользователь не дал ответ (или дал непонятно) - задай уточняющий вопрос 1 предложением. "
            "- Если пользователь ответил голосом, обрати внимание на построение фразы и похвали за Speaking."
        )

    def transcribe_audio(self, wav_file_path: str) -> str:
        with open(wav_file_path, "rb") as file:
            transcription = self.groq_client.audio.transcriptions.create(
                file=(wav_file_path, file.read()),
                model=settings.stt.model_id,
                response_format="text",
            )
        return transcription

    async def get_text_response(self, history_messages: list) -> str:
        provider = settings.llm.active_text_provider
        if provider == "gemini":
            return await self._call_gemini(history_messages)
        if provider == "groq":
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
                temperature=cfg.temperature,
            ),
        )
        return response.text

    async def _call_groq(self, history: list) -> str:
        cfg = settings.llm.groq
        messages = [{"role": "system", "content": self.system_instruction}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["text"]})

        loop = asyncio.get_running_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: self.groq_client.chat.completions.create(
                model=cfg.model_id,
                messages=messages,
                temperature=cfg.temperature,
            ),
        )
        return completion.choices[0].message.content


ai = AIProviderManager()
