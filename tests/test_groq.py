import os
from unittest.mock import patch

import pytest

from groq_service import GroqAskService


class TestGroqAskServiceInit:
    def test_no_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GROQ_API_KEY"):
                GroqAskService(api_key=None)

    def test_constructor_api_key_used(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "env-key"}, clear=True):
            service = GroqAskService()
            assert service._model == "openai/gpt-oss-120b"

    def test_model_from_env_var(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL": "env-model"}, clear=True):
            service = GroqAskService()
            assert service._model == "env-model"

    def test_model_from_constructor_arg(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True):
            service = GroqAskService(model="arg-model")
            assert service._model == "arg-model"

    def test_env_var_overrides_constructor(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_MODEL": "env-model"}, clear=True):
            service = GroqAskService(model="arg-model")
            assert service._model == "env-model"

    def test_default_model_used(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=True):
            service = GroqAskService()
            assert service._model == "openai/gpt-oss-120b"
