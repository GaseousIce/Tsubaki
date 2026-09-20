import logging
import re

import discord
from discord import app_commands

import db
from anti_phishing import domain
from groq_service import ask_tsubaki

logger = logging.getLogger("discord")

_MSG_LINK_RE = re.compile(r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/\d+/(\d+)/(\d+)")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _is_image_attachment(att: discord.Attachment) -> bool:
    ct = getattr(att, "content_type", None)
    if isinstance(ct, str) and ct.startswith("image/"):
        return True
    filename = getattr(att, "filename", None)
    if isinstance(filename, str):
        return any(filename.lower().endswith(ext) for ext in _IMAGE_EXTS)
    return False


def _resolve_gallery_url(message: discord.Message) -> str:
    raw_jump = getattr(message, "jump_url", None)
    if isinstance(raw_jump, str) and raw_jump.startswith("http"):
        return raw_jump
    guild = getattr(message, "guild", None)
    guild_id = getattr(guild, "id", None)
    channel = getattr(message, "channel", None)
    channel_id = getattr(channel, "id", None)
    msg_id = getattr(message, "id", None)
    if isinstance(guild_id, (int, str)) and isinstance(channel_id, (int, str)) and isinstance(msg_id, (int, str)):
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
    return "https://discord.com"


def _parse_message_reference(ref: str) -> tuple[int | None, int | None]:
    ref = ref.strip()
    match = _MSG_LINK_RE.match(ref)
    if match:
        try:
            return int(match.group(1)), int(match.group(2))
        except ValueError:
            return None, None
    try:
        return None, int(ref)
    except ValueError:
        return None, None


async def _fetch_target_message(
    guild: discord.Guild,
    channel: discord.abc.Messageable,
    channel_id: int | None,
    message_id: int,
) -> discord.Message | None:
    if channel_id:
        target_ch = guild.get_channel(channel_id)
        if target_ch and hasattr(target_ch, "fetch_message"):
            try:
                return await target_ch.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

    if hasattr(channel, "fetch_message"):
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    for ch in guild.text_channels:
        if ch.id == getattr(channel, "id", None):
            continue
        try:
            return await ch.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

    return None


def _resolve_log_channel(
    guild: discord.Guild,
    fallback_channel: discord.abc.Messageable,
    alert_channel_ids: list[int] | None = None,
) -> discord.abc.Messageable:
    me = guild.me
    if alert_channel_ids:
        for cid in alert_channel_ids:
            ch = guild.get_channel(cid)
            if ch and hasattr(ch, "send"):
                if me:
                    perms = ch.permissions_for(me)
                    if perms.view_channel and perms.send_messages and perms.embed_links:
                        return ch
                else:
                    return ch

    for ch in guild.text_channels:
        name = ch.name.lower()
        if "log" in name or "alert" in name:
            if me:
                perms = ch.permissions_for(me)
                if perms.view_channel and perms.send_messages and perms.embed_links:
                    return ch
            else:
                return ch

    return fallback_channel


def _build_test_log_embeds(
    message: discord.Message,
    detected_url: str | None,
    reason: str | None,
    tester: discord.User | discord.Member,
) -> list[discord.Embed]:
    guild_name = message.guild.name if message.guild else "Unknown Guild"
    color = discord.Color.red() if reason else discord.Color.green()
    embed = discord.Embed(
        title="🧪 Test Log — Message Inspection",
        description=(
            f"**Author:** {message.author.mention} (`{message.author}`, ID: `{message.author.id}`)\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Message ID:** `{message.id}` ([Jump to Message]({message.jump_url}))\n"
            f"**Phishing URL Detected:** `{detected_url or 'None'}`\n"
            f"**Detection Reason:** `{reason or 'Clean (No threat detected)'}`\n"
            f"**Action Taken:** `None (Test Mode — Message and user untouched)`"
        ),
        color=color,
        timestamp=discord.utils.utcnow(),
    )

    content_text = getattr(message, "content", "") or ""
    if content_text.strip():
        preview = content_text if len(content_text) <= 1000 else content_text[:997] + "..."
        embed.add_field(name="Message Content", value=preview, inline=False)
    else:
        embed.add_field(name="Message Content", value="*(No text content)*", inline=False)

    raw_embeds = getattr(message, "embeds", [])
    if raw_embeds:
        embed_summaries = []
        for i, emb in enumerate(raw_embeds[:3], start=1):
            parts = []
            if getattr(emb, "title", None):
                parts.append(f"**Title:** {emb.title}")
            if getattr(emb, "description", None):
                desc = emb.description if len(emb.description) <= 200 else emb.description[:197] + "..."
                parts.append(f"**Description:** {desc}")
            if getattr(emb, "url", None):
                parts.append(f"**URL:** {emb.url}")
            if parts:
                embed_summaries.append(f"__Embed #{i}__\n" + "\n".join(parts))
        if embed_summaries:
            embed_text = "\n\n".join(embed_summaries)
            if len(embed_text) > 1024:
                embed_text = embed_text[:1021] + "..."
            embed.add_field(name=f"Original Embeds ({len(raw_embeds)})", value=embed_text, inline=False)

    raw_attachments = getattr(message, "attachments", [])
    if raw_attachments:
        att_lines = []
        for a in raw_attachments[:5]:
            fname = getattr(a, "filename", "attachment")
            a_url = getattr(a, "url", None)
            raw_size = getattr(a, "size", None)
            size = raw_size if isinstance(raw_size, int) else 0
            size_str = f" ({size // 1024} KB)" if size >= 1024 else (f" ({size} B)" if size > 0 else "")
            if a_url:
                att_lines.append(f"• [{fname}]({a_url}){size_str}")
            else:
                att_lines.append(f"• {fname}{size_str}")
        if len(raw_attachments) > 5:
            att_lines.append(f"*(and {len(raw_attachments) - 5} more)*")
        att_value = "\n".join(att_lines)
        if len(att_value) > 1024:
            att_value = att_value[:1021] + "..."
        embed.add_field(name=f"Attachments ({len(raw_attachments)})", value=att_value, inline=False)

    image_urls: list[str] = [
        att.url for att in raw_attachments if getattr(att, "url", None) and _is_image_attachment(att)
    ]
    if len(image_urls) < 4 and raw_embeds:
        for emb in raw_embeds[:3]:
            img_url = getattr(getattr(emb, "image", None), "url", None) or getattr(
                getattr(emb, "thumbnail", None), "url", None
            )
            if img_url and img_url not in image_urls:
                image_urls.append(img_url)
            if len(image_urls) >= 4:
                break

    embed.set_footer(text=f"Tested by {tester} | Guild: {guild_name}")

    embeds = [embed]
    if image_urls:
        if len(image_urls) == 1:
            embed.set_image(url=image_urls[0])
        else:
            gallery_url = _resolve_gallery_url(message)
            embed.url = gallery_url
            embed.set_image(url=image_urls[0])
            for extra_url in image_urls[1:4]:
                sub_embed = discord.Embed(url=gallery_url)
                sub_embed.set_image(url=extra_url)
                embeds.append(sub_embed)

    return embeds


def _build_test_log_embed(
    message: discord.Message,
    detected_url: str | None,
    reason: str | None,
    tester: discord.User | discord.Member,
) -> discord.Embed:
    return _build_test_log_embeds(message, detected_url, reason, tester)[0]


def setup(bot, groq_model: str = "openai/gpt-oss-120b") -> None:
    """Register /hello, /ping, /ask, and /test commands on the bot.

    The bot must have an ``ai_service`` attribute (set to an ``AsyncGroq``
    client or ``None``) before /ask is invoked.  Setting it to ``None``
    disables the command gracefully.
    """

    @bot.tree.command(name="hello", description="Say hello to Tsubaki")
    async def hello(interaction: discord.Interaction):
        await interaction.response.send_message("hello there! :3")

    @bot.tree.command(name="ping", description="Check if the bot is online")
    async def ping(interaction: discord.Interaction):
        latency_ms = round(bot.latency * 1000)
        await interaction.response.send_message(f"Pong! {latency_ms} ms")

    @bot.tree.command(name="ask", description="Ask Tsubaki anything")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def ask(interaction: discord.Interaction, question: str):
        ai_service = getattr(bot, "ai_service", None)
        if ai_service is None:
            await interaction.response.send_message("The Groq API key is not configured yet.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            async with interaction.channel.typing():
                answer = await ask_tsubaki(ai_service, question, model=groq_model)
        except Exception:
            logger.exception("Groq request for /ask failed")
            await interaction.followup.send(
                "Uuu... (╥﹏╥) My brainwaves got all tangled up! I couldn't reach my thoughts right now. "
                "Please try asking me again in a bit, okay? (｡>﹏<｡)"
            )
            return

        if len(answer) > 2000:
            answer = f"{answer[:1997]}..."

        await interaction.followup.send(answer)

    @ask.error
    async def ask_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        try:
            if isinstance(error, app_commands.CommandOnCooldown):
                await interaction.response.send_message(
                    f"H-Hey! Don't spam me! ( ｀皿´) Please wait {error.retry_after:.1f}s before asking again, baka!",
                    ephemeral=True,
                )
            else:
                logger.error("Unhandled error in /ask command: %s", error)
                target = (
                    interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
                )
                await target("An error occurred.", ephemeral=True)
        except discord.HTTPException:
            pass

    @bot.tree.command(
        name="test",
        description="Inspect a message by ID and log it to the logs channel without taking action",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(message_id="Message ID or link to inspect and log")
    async def test_cmd(interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("❌ This command can only be used in a server.", ephemeral=True)
            return

        cid, mid = _parse_message_reference(message_id)
        if mid is None:
            await interaction.followup.send(
                "❌ Invalid message ID. Please provide a numeric message ID or message link.", ephemeral=True
            )
            return

        target_message = await _fetch_target_message(interaction.guild, interaction.channel, cid, mid)
        if target_message is None:
            await interaction.followup.send(
                f"❌ Could not find message `{mid}` in accessible channels.", ephemeral=True
            )
            return

        try:
            guild_cfg = await db.get_or_create_guild_config(interaction.guild_id)
            alert_channels = guild_cfg.get("alert_channels", [])
        except Exception as exc:
            logger.warning("Failed to fetch guild config in /test: %s", exc)
            alert_channels = []

        log_channel = _resolve_log_channel(interaction.guild, interaction.channel, alert_channels)

        detected_url = None
        reason = None
        try:
            urls = domain.extract_urls(target_message.content, target_message.embeds, target_message.attachments)
            if urls:
                detected_url, reason = await domain.find_in_blacklists(urls)
        except Exception as exc:
            logger.warning("Error inspecting message %s: %s", mid, exc)

        embeds = _build_test_log_embeds(target_message, detected_url, reason, interaction.user)

        try:
            if len(embeds) > 1:
                await log_channel.send(embeds=embeds)
            else:
                await log_channel.send(embed=embeds[0])
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ Missing permission to send messages or embed links in {log_channel.mention}.", ephemeral=True
            )
            return
        except Exception as exc:
            logger.exception("Failed to send test log embed: %s", exc)
            await interaction.followup.send(f"❌ Failed to send log to {log_channel.mention}: {exc}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Message `{mid}` logged to {log_channel.mention}. No action was taken against the message or user.",
            ephemeral=True,
        )
