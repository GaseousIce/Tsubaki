"""Tier 4: Real-World Application Scenarios.

Simulates complex, high-fidelity production scenarios:
- Realistic server workloads with mixed chatter and concurrent slash commands
- Surgical moderation under high-volume chatter (only threat deleted)
- Multi-guild isolation under concurrent load
- Coordinated multi-bot raid simulations
- Multi-channel link spreading spambot raid simulations
- Adversarial evasion attacks (subdomains, case alteration, punctuation)
"""

from .helpers import (
    create_admin_member,
    create_regular_member,
    grant_bot_permissions,
    set_guild_alert_channel,
)


class TestTier4RealWorldScenarios:
    """Opaque-box real-world and adversarial raid simulation test suite."""

    async def test_scenario_realistic_server_workload(self, simcord_env):
        """Simulate active daily server workload: chat, safe URLs, slash commands, and stats check."""
        guild = simcord_env.create_guild()
        general = guild.create_text_channel("general")
        dev = guild.create_text_channel("dev-chat")
        admin = create_admin_member(simcord_env, guild, "admin")
        alice = create_regular_member(simcord_env, guild, "alice")
        bob = create_regular_member(simcord_env, guild, "bob")
        charlie = create_regular_member(simcord_env, guild, "charlie")

        # 1. Members chat actively
        await alice.send(general, "Good morning everyone!")
        await bob.send(general, "Morning Alice! Working on the new release today?")
        await charlie.send(dev, "Check out the PR here: https://github.com/org/repo/pull/12")
        await alice.send(dev, "Looks good, I also checked https://docs.python.org/3/library/asyncio.html")

        # 2. Members run utility slash commands
        res_ping = await bob.slash(general, "ping")
        assert "Pong!" in res_ping.response.content

        res_hello = await charlie.slash(dev, "hello")
        assert res_hello.response.content == "hello there! :3"

        # 3. Admin checks stats
        res_stats = await admin.slash(general, "antiphishing stats")
        assert res_stats.followups
        assert "Anti-Phishing Stats" in res_stats.followups[0].embeds[0].title

        # Verify chat integrity: all legitimate messages preserved
        assert len(general.history()) == 3  # alice, bob, bot hello/ping
        assert len(dev.history()) == 3  # charlie, alice, bot hello
        assert all(m.member.timed_out_until is None for m in [alice, bob, charlie])

    async def test_scenario_surgical_moderation_under_mixed_traffic(self, simcord_env, official_domains):
        """Under heavy conversation, an injected phishing link is surgically deleted while preserving chat."""
        guild = simcord_env.create_guild()
        chat_ch = guild.create_text_channel("lounge")
        alerts_ch = guild.create_text_channel("mod-alerts")
        await grant_bot_permissions(
            simcord_env,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await set_guild_alert_channel(guild.id, alerts_ch.id)

        alice = create_regular_member(simcord_env, guild, "alice")
        bob = create_regular_member(simcord_env, guild, "bob")
        hacker = create_regular_member(simcord_env, guild, "compromised_user")

        target_domain = next(iter(official_domains))

        # Innocent chat begins
        await alice.send(chat_ch, "Hey Bob, have you played the new game yet?")
        await bob.send(chat_ch, "Yeah! The graphics are incredible.")

        # Threat is injected by compromised account
        await hacker.send(chat_ch, f"FREE STEAM GIFT CARD: https://{target_domain}/gift-card")

        # Innocent conversation continues
        await alice.send(chat_ch, "Wait what was that?")
        await bob.send(chat_ch, "Looks like auto-mod already caught it!")

        # Exactly 4 innocent messages remain in history; threat was removed
        history = chat_ch.history()
        assert len(history) == 4
        assert not any(target_domain in m.content for m in history)

        # Attacker is timed out; innocent users are untouched
        assert hacker.member.timed_out_until is not None
        assert alice.member.timed_out_until is None
        assert bob.member.timed_out_until is None

        # Exactly 1 alert recorded
        assert len(alerts_ch.history()) == 1

    async def test_scenario_multi_guild_isolation_under_load(self, simcord_env, official_domains):
        """Attacks and moderations in Guild 1 have zero impact or leak on Guild 2."""
        guild1 = simcord_env.create_guild()
        guild2 = simcord_env.create_guild()

        g1_chat = guild1.create_text_channel("g1-chat")
        g1_alerts = guild1.create_text_channel("g1-alerts")
        g2_chat = guild2.create_text_channel("g2-chat")
        g2_alerts = guild2.create_text_channel("g2-alerts")

        await grant_bot_permissions(
            simcord_env,
            guild1,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await grant_bot_permissions(
            simcord_env,
            guild2,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )

        await set_guild_alert_channel(guild1.id, g1_alerts.id)
        await set_guild_alert_channel(guild2.id, g2_alerts.id)

        attacker_g1 = create_regular_member(simcord_env, guild1, "attacker_g1")
        innocent_g2 = create_regular_member(simcord_env, guild2, "innocent_g2")

        target_domain = next(iter(official_domains))

        # Innocent message in Guild 2
        await innocent_g2.send(g2_chat, "Peaceful day in server two!")

        # Attack executed in Guild 1
        await attacker_g1.send(g1_chat, f"Phishing payload https://{target_domain}/login")

        # Guild 1 was moderated
        assert len(g1_chat.history()) == 0
        assert attacker_g1.member.timed_out_until is not None
        assert len(g1_alerts.history()) == 1

        # Guild 2 is completely pristine
        assert len(g2_chat.history()) == 1
        assert len(g2_alerts.history()) == 0
        assert innocent_g2.member.timed_out_until is None

    async def test_scenario_coordinated_multi_bot_raid_simulation(self, simcord_env, official_domains):
        """Coordinated raid with 3 distinct accounts blasting phishing links is completely neutralized."""
        guild = simcord_env.create_guild()
        chat1 = guild.create_text_channel("chat-1")
        chat2 = guild.create_text_channel("chat-2")
        chat3 = guild.create_text_channel("chat-3")
        alerts = guild.create_text_channel("mod-alerts")

        await grant_bot_permissions(
            simcord_env,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await set_guild_alert_channel(guild.id, alerts.id)

        raider1 = create_regular_member(simcord_env, guild, "raider_1")
        raider2 = create_regular_member(simcord_env, guild, "raider_2")
        raider3 = create_regular_member(simcord_env, guild, "raider_3")

        domain_list = list(official_domains)
        d1 = domain_list[0]
        d2 = domain_list[1] if len(domain_list) > 1 else d1
        d3 = domain_list[2] if len(domain_list) > 2 else d1

        # Simultaneous raid drop
        await raider1.send(chat1, f"Raider 1 drop: https://{d1}/loot")
        await raider2.send(chat2, f"Raider 2 drop: https://{d2}/loot")
        await raider3.send(chat3, f"Raider 3 drop: https://{d3}/loot")

        # All raid messages purged across all channels
        assert len(chat1.history()) == 0
        assert len(chat2.history()) == 0
        assert len(chat3.history()) == 0

        # All 3 raiders timed out
        assert raider1.member.timed_out_until is not None
        assert raider2.member.timed_out_until is not None
        assert raider3.member.timed_out_until is not None

        # 3 distinct alerts sent to mod-alerts channel
        assert len(alerts.history()) == 3

    async def test_scenario_multi_channel_spambot_raid_simulation(self, simcord_env_rate):
        """Spambot attempting multi-channel raid spreading is stopped by rate-limit heuristic."""
        guild = simcord_env_rate.create_guild()
        channels = [guild.create_text_channel(f"channel-{i}") for i in range(5)]
        alerts = guild.create_text_channel("alerts")

        await grant_bot_permissions(
            simcord_env_rate,
            guild,
            moderate_members=True,
            manage_messages=True,
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        await set_guild_alert_channel(guild.id, alerts.id)

        spambot = create_regular_member(simcord_env_rate, guild, "spambot")

        # Spambot rapidly posts suspicious links across channels
        for i, ch in enumerate(channels[:3]):
            await spambot.send(ch, f"Check this out: https://suspicious-spread-domain.com/item{i}")

        # Rate limit triggered by 3rd channel
        assert spambot.member.timed_out_until is not None
        assert len(alerts.history()) >= 1
        assert "rate_limit" in alerts.history()[0].embeds[0].description

    async def test_scenario_evasion_tactics_subdomains_and_paths(self, simcord_env, official_domains):
        """Attacker using subdomains (sub.evil.com) and deep paths is caught by domain suffix analysis."""
        guild = simcord_env.create_guild()
        channel = guild.create_text_channel("chat")
        alice = create_regular_member(simcord_env, guild, "alice")
        await grant_bot_permissions(simcord_env, guild, moderate_members=True, manage_messages=True)

        target_domain = next(iter(official_domains))

        # Attacker attempts subdomain evasion
        subdomain_url = f"https://promo.auth.verify.{target_domain}/deep/nested/path?id=123"
        await alice.send(channel, f"Urgent verification: {subdomain_url}")

        assert len(channel.history()) == 0
        assert alice.member.timed_out_until is not None
