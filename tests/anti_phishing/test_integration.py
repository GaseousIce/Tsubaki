class TestHello:
    async def test_hello_command(self, simcord_env):
        channel = simcord_env.create_guild().create_text_channel("general")
        alice = simcord_env.guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "hello")
        assert result.response.content == "hello there! :3"

    async def test_ping_command(self, simcord_env):
        channel = simcord_env.create_guild().create_text_channel("general")
        alice = simcord_env.guild.add_member(simcord_env.create_user("alice"))

        result = await alice.slash(channel, "ping")
        assert "ms" in result.response.content
