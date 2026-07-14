from unittest.mock import AsyncMock, MagicMock, patch


class TestAskCommand:
    async def test_ask_no_ai_service(self, simcord_env):
        """When ai_service is None, /ask replies with a disabled message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        # ai_service is None by default in the test bot
        result = await alice.slash(channel, "ask", question="Hello?")
        assert result.response.content == "The Groq API key is not configured yet."

    async def test_ask_success(self, simcord_env):
        """When ai_service is set and ask_tsubaki returns, /ask sends the answer."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value="Hii~ (´｡• ᵕ •｡`)"):
            result = await alice.slash(channel, "ask", question="Hello?")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert followup.content == "Hii~ (´｡• ᵕ •｡`)"

    async def test_ask_groq_failure(self, simcord_env):
        """When ask_tsubaki raises, /ask sends the error personality message."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        with patch("commands.ask_tsubaki", new_callable=AsyncMock, side_effect=Exception("API down")):
            result = await alice.slash(channel, "ask", question="Hello?")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert "brainwaves" in followup.content

    async def test_ask_truncates_long_response(self, simcord_env):
        """Responses over 2000 chars are truncated with '...'."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("general")
        alice = guild.add_member(simcord_env.create_user("alice"))

        mock_client = MagicMock()
        simcord_env.bot.ai_service = mock_client

        long_answer = "a" * 2500
        with patch("commands.ask_tsubaki", new_callable=AsyncMock, return_value=long_answer):
            result = await alice.slash(channel, "ask", question="Write a novel")

        followup = result.followups[0] if result.followups else None
        assert followup is not None
        assert len(followup.content) == 2000
        assert followup.content.endswith("...")
