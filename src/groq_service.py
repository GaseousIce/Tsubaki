import os

from groq import AsyncGroq


class GroqAskService:
    """Small wrapper around the Groq Chat Completions API for /ask."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        resolved_api_key = api_key or os.getenv("GROQ_API_KEY")
        if not resolved_api_key:
            raise ValueError("GROQ_API_KEY is not set")

        self._model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self._client = AsyncGroq(api_key=resolved_api_key)

    async def ask(self, question: str) -> str:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Tsubaki, a helpful Discord assistant with a cute "
                        "weeb anime-girl vibe. Keep replies concise and friendly, but "
                        "do not use forced playful wording. Prefer Japanglish with "
                        "weeb slang and anime-style phrasing to make the reply funnier. "
                        "Include clearly visible, varied kaomojis in "
                        "every reply, and use more than one in longer replies. Avoid "
                        "repeating the same kaomojis too often. Use line breaks "
                        "liberally so different thoughts or points are separated "
                        "clearly, especially in longer replies."
                    ),
                },
                {"role": "user", "content": question},
            ],
            temperature=0.8,
            max_tokens=500,
        )

        text = (completion.choices[0].message.content or "").strip()
        if text:
            return text

        return "I could not generate a response right now. Please try again."
