import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from groq_service import ask_tsubaki, get_groq_client


class TestGetGroqClient:
    def test_no_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GROQ_API_KEY"):
                get_groq_client(api_key=None)

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "env-key"}, clear=True):
            client = get_groq_client()
            assert client is not None


class TestAskTsubaki:
    async def test_ask_returns_answer(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Hello there! (´｡• ᵕ •｡`)"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!", model="test-model")
        assert result == "Hello there! (´｡• ᵕ •｡`)"
        mock_client.chat.completions.create.assert_awaited_once()

    async def test_ask_empty_response_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = ""
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."
