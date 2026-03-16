import os

from openai import AsyncOpenAI


class OpenAIAskService:
    """Small wrapper around the OpenAI Responses API for the /ask command."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = AsyncOpenAI(api_key=resolved_api_key)

    async def ask(self, question: str) -> str:
        response = await self._client.responses.create(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are Tsubaki, a helpful Discord assistant with a cute "
                                "weeb anime-girl vibe. Keep replies concise and friendly, "
                                "use playful anime-style wording, and include lots of "
                                "kaomojis in most sentences (for example: (^-^), (>w<), "
                                "(o^.^o), (uwu))."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": question}],
                },
            ],
            max_output_tokens=500,
        )

        text = (response.output_text or "").strip()
        if text:
            return text

        return "I could not generate a response right now. Please try again."
