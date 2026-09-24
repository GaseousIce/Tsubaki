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
            assert client.timeout == 15.0

    def test_custom_timeout(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "env-key"}, clear=True):
            client = get_groq_client(timeout=30.0)
            assert client.timeout == 30.0


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

    async def test_ask_passes_timeout(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Response"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        await ask_tsubaki(mock_client, "Hello")
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs.get("timeout") == 15.0

    async def test_ask_custom_timeout(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Response"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        await ask_tsubaki(mock_client, "Hello", timeout=25.0)
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs.get("timeout") == 25.0

    async def test_ask_empty_response_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = ""
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."

    async def test_ask_empty_choices_list_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = []
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."

    async def test_ask_none_choices_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."

    async def test_ask_choice_message_is_none_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=None)]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."

    async def test_ask_choice_content_none_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content=None))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."

    async def test_ask_whitespace_response_falls_back(self):
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock(message=MagicMock(content="   \n\t  "))]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        result = await ask_tsubaki(mock_client, "Hi!")
        assert result == "I could not generate a response right now. Please try again."
