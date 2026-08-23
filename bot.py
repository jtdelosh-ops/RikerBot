from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("riker-bot")

BASE_DIR = Path(__file__).resolve().parent
QUOTES_PATH = BASE_DIR / "quotes.json"
STATE_PATH = BASE_DIR / "riker_state.json"

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0") or 0)


def parse_channel_ids() -> list[int]:
    """Load approved text-channel IDs from the environment."""
    raw = os.getenv("RIKER_CHANNEL_IDS", "").strip() or os.getenv("RIKER_CHANNEL_ID", "").strip()
    if not raw:
        return []
    channel_ids: list[int] = []
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            channel_ids.append(int(value))
        except ValueError:
            log.warning("Ignoring invalid channel ID in environment: %r", value)
    return list(dict.fromkeys(channel_ids))


RIKER_CHANNEL_IDS = parse_channel_ids()
RIKER_QUOTE_CHANCE = max(0.0, min(1.0, float(os.getenv("RIKER_QUOTE_CHANCE", "0.70"))))
RIKER_GENERATED_REMARK_CHANCE = max(
    0.0, min(1.0, float(os.getenv("RIKER_GENERATED_REMARK_CHANCE", "0.20")))
)
RIKER_RECENT_QUOTE_HISTORY_SIZE = max(
    0, int(os.getenv("RIKER_RECENT_QUOTE_HISTORY_SIZE", "10") or 10)
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
RIKER_ADVICE_COOLDOWN_SECONDS = max(
    0, int(os.getenv("RIKER_ADVICE_COOLDOWN_SECONDS", "30") or 30)
)

RIKER_TIMEZONE = ZoneInfo("America/New_York")
RIKER_POST_START_HOUR = 9
RIKER_POST_END_HOUR = 21


@dataclass
class RikerState:
    recent_quote_ids: list[str] = field(default_factory=list)
    last_spontaneous_post: str | None = None


@dataclass
class SendResult:
    success: bool
    reason: str
    channel_id: int | None = None
    channel_name: str | None = None
    content_kind: str | None = None


def load_state(path: Path = STATE_PATH) -> RikerState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state root is not an object")
        recent = data.get("recent_quote_ids", [])
        last_post = data.get("last_spontaneous_post")
        if not isinstance(recent, list):
            recent = []
        return RikerState(
            recent_quote_ids=[str(value) for value in recent if value],
            last_spontaneous_post=str(last_post) if last_post else None,
        )
    except FileNotFoundError:
        return RikerState()
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        log.warning("Ignoring unreadable Riker state file %s: %s", path, exc)
        return RikerState()


def save_state(state: RikerState, path: Path = STATE_PATH) -> None:
    """Persist lightweight state through a temporary file and atomic replace."""
    payload = {
        "recent_quote_ids": state.recent_quote_ids,
        "last_spontaneous_post": state.last_spontaneous_post,
    }
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(path)
    except OSError:
        log.exception("Could not save Riker state to %s", path)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


riker_state = load_state()


def load_quotes() -> list[dict[str, str]]:
    try:
        data = json.loads(QUOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not load %s: %s", QUOTES_PATH, exc)
        return []
    valid: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).strip()
        source = str(item.get("source", "")).strip()
        if quote:
            valid.append({"quote": quote, "source": source})
    return valid


def quote_identity(item: dict[str, str]) -> str:
    return " ".join(item["quote"].casefold().split())


def choose_quote(
    recent_quote_ids: list[str] | None = None, *, rng: random.Random | Any = random
) -> dict[str, str] | None:
    """Choose outside recent history when the library permits it."""
    quotes = load_quotes()
    if not quotes:
        return None
    recent = set(recent_quote_ids or [])
    eligible = [item for item in quotes if quote_identity(item) not in recent]
    return rng.choice(eligible or quotes)


def record_quote_used(
    item: dict[str, str], state: RikerState = riker_state, path: Path = STATE_PATH
) -> None:
    identity = quote_identity(item)
    state.recent_quote_ids = [value for value in state.recent_quote_ids if value != identity]
    state.recent_quote_ids.append(identity)
    if RIKER_RECENT_QUOTE_HISTORY_SIZE:
        state.recent_quote_ids = state.recent_quote_ids[-RIKER_RECENT_QUOTE_HISTORY_SIZE:]
    else:
        state.recent_quote_ids = []
    save_state(state, path)


def eastern_time(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(RIKER_TIMEZONE)
    if now.tzinfo is None:
        return now.replace(tzinfo=RIKER_TIMEZONE)
    return now.astimezone(RIKER_TIMEZONE)


def is_within_posting_hours(now: datetime | None = None) -> bool:
    current = eastern_time(now)
    return RIKER_POST_START_HOUR <= current.hour < RIKER_POST_END_HOUR


def parse_state_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return eastern_time(datetime.fromisoformat(value))
    except ValueError:
        return None


def effective_quote_chance(
    now: datetime, base_chance: float = RIKER_QUOTE_CHANCE, last_post: datetime | None = None
) -> float:
    """Apply small time-of-day and recent-posting adjustments."""
    current = eastern_time(now)
    multiplier = 0.65 if current.hour < 11 else 1.15 if current.hour >= 17 else 1.0
    if last_post is not None:
        elapsed_hours = (current - eastern_time(last_post)).total_seconds() / 3600
        if 0 <= elapsed_hours < 2:
            multiplier *= 0.5
    return max(0.0, min(1.0, base_chance * multiplier))


def quote_embed(item: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(description=f'“{item["quote"]}”', title="Commander Riker")
    if item.get("source"):
        embed.set_footer(text=item["source"])
    return embed


def generated_remark_embed(text: str) -> discord.Embed:
    embed = discord.Embed(description=text, title="Commander Riker")
    embed.set_footer(text="Original RikerBot remark")
    return embed


RIKER_PERSONA = """
You are the personality engine for a lighthearted Discord bot inspired by
Commander William Riker from Star Trek: The Next Generation.

Capture broad traits rather than copying scripts:
- confident, composed, charismatic, capable
- dry humor and occasional playful swagger
- warm toward the crew
- pragmatic when giving advice
- willing to tease someone when the situation calls for it
- occasionally uses a Starfleet-flavored form of address such as "Lieutenant"
  or "Ensign", but do not do it every time

Rules:
- Keep the response concise: usually 1-4 sentences.
- Write new dialogue. Do not reproduce or continue dialogue from Star Trek.
- Do not pretend a generated line is a real quotation from the show.
- Avoid excessive catchphrases and constant Star Trek references.
- If the user asks a serious factual question, be useful first and in-character second.
""".strip()


class RikerBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        )
        self.advice_last_used: dict[int, float] = {}

    async def setup_hook(self) -> None:
        self.tree.add_command(RikerCommands(self))
        if DISCORD_GUILD_ID:
            guild = discord.Object(id=DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s", len(synced), DISCORD_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global command(s)", len(synced))
        if RIKER_CHANNEL_IDS:
            riker_quote_scheduler.start()
            log.info("Riker roaming enabled across %d approved channel(s).", len(RIKER_CHANNEL_IDS))
        else:
            log.warning(
                "RIKER_CHANNEL_IDS is not set; scheduled appearances are disabled. "
                "Slash commands will still work."
            )

    async def on_ready(self) -> None:
        if self.user:
            log.info("Logged in as %s (%s)", self.user, self.user.id)


bot = RikerBot()


async def resolve_riker_channel(
    client: RikerBot, channel_id: int
) -> tuple[discord.TextChannel | discord.Thread | None, str | None]:
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except discord.Forbidden:
            return None, f"Discord denied access to channel {channel_id}."
        except discord.NotFound:
            return None, f"Configured channel {channel_id} was not found."
        except discord.DiscordException as exc:
            return None, f"Could not resolve channel {channel_id}: {exc}"
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None, f"Configured channel {channel_id} is not a text channel or thread."
    return channel, None


def inspect_channel_permissions(
    client: RikerBot, channel: discord.TextChannel | discord.Thread
) -> dict[str, bool | None]:
    guild = getattr(channel, "guild", None)
    member = getattr(guild, "me", None) or (
        guild.get_member(client.user.id) if guild and client.user else None
    )
    if member is None:
        return {"view_channel": None, "send_messages": None, "embed_links": None}
    permissions = channel.permissions_for(member)
    return {
        "view_channel": bool(permissions.view_channel),
        "send_messages": bool(permissions.send_messages),
        "embed_links": bool(permissions.embed_links),
    }


async def generate_spontaneous_remark(client: RikerBot) -> str | None:
    if not client.openai:
        return None
    try:
        response = await client.openai.responses.create(
            model=OPENAI_MODEL,
            instructions=RIKER_PERSONA,
            input=(
                "Write one short original remark for a spontaneous Discord appearance. "
                "Keep it to one or two sentences. Do not quote or cite Star Trek."
            ),
            max_output_tokens=100,
        )
        return (response.output_text or "").strip() or None
    except Exception:
        log.exception("Could not generate a spontaneous Riker remark; using a quote")
        return None


def permission_failure_reason(permissions: dict[str, bool | None]) -> str | None:
    missing = [name for name, allowed in permissions.items() if allowed is False]
    if not missing:
        return None
    labels = {
        "view_channel": "View Channel",
        "send_messages": "Send Messages",
        "embed_links": "Embed Links",
    }
    return "Missing Discord permission(s): " + ", ".join(labels[name] for name in missing)


async def send_spontaneous_quote(
    client: RikerBot, channel_id: int | None = None, *, generated_roll: float | None = None
) -> SendResult:
    """Resolve, validate, and send one spontaneous appearance.

    This is deliberately the sole automatic ``channel.send(...)`` path. The
    scheduler and /riker test_auto both call it so diagnostics exercise the
    same lookup, permissions, embed, and error handling as production.
    """
    if channel_id is None:
        if not RIKER_CHANNEL_IDS:
            return SendResult(False, "No target channels are configured.")
        channel_id = random.choice(RIKER_CHANNEL_IDS)
    channel, error = await resolve_riker_channel(client, channel_id)
    if channel is None:
        return SendResult(False, error or "Channel resolution failed.", channel_id)

    channel_name = getattr(channel, "name", str(channel_id))
    permission_error = permission_failure_reason(inspect_channel_permissions(client, channel))
    if permission_error:
        return SendResult(False, permission_error, channel_id, channel_name)

    roll = random.random() if generated_roll is None else generated_roll
    remark = await generate_spontaneous_remark(client) if roll < RIKER_GENERATED_REMARK_CHANCE else None
    item: dict[str, str] | None = None
    if remark:
        embed = generated_remark_embed(remark)
        content_kind = "original remark"
    else:
        item = choose_quote(riker_state.recent_quote_ids)
        if item is None:
            return SendResult(
                False, "No valid quotes are available in quotes.json.", channel_id, channel_name
            )
        embed = quote_embed(item)
        content_kind = "static quote"

    try:
        # Keep this centralized: test_auto must exercise this exact send.
        await channel.send(embed=embed)
    except discord.Forbidden as exc:
        code = getattr(exc, "code", None)
        suffix = f" (Discord error {code})" if code else ""
        return SendResult(
            False,
            "Discord rejected the post as Missing Permissions"
            f"{suffix}. Check View Channel, Send Messages, and Embed Links.",
            channel_id,
            channel_name,
            content_kind,
        )
    except discord.HTTPException as exc:
        return SendResult(
            False,
            f"Discord could not send the embed: {exc}",
            channel_id,
            channel_name,
            content_kind,
        )

    if item is not None:
        record_quote_used(item)
    riker_state.last_spontaneous_post = datetime.now(RIKER_TIMEZONE).isoformat()
    save_state(riker_state)
    return SendResult(True, f"Sent a {content_kind}.", channel_id, channel_name, content_kind)


def format_permission(value: bool | None) -> str:
    return "yes" if value is True else "no" if value is False else "unknown"


class RikerCommands(app_commands.Group):
    def __init__(self, client: RikerBot) -> None:
        super().__init__(name="riker", description="Commander Riker has the conn.")
        self.client = client

    @app_commands.command(name="help", description="Learn how to use RikerBot.")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Commander Riker — Help", description="The Commander is ready to assist.")
        embed.add_field(name="/riker quote", value="Posts a non-repeating line from Riker's configured library.", inline=False)
        embed.add_field(name="/riker advice question:<your question>", value="Ask for a concise Riker-flavored take when AI mode is enabled.", inline=False)
        embed.add_field(name="/riker status", value="Shows scheduler, channel permission, AI, and recent-post diagnostics.", inline=False)
        embed.add_field(
            name="/riker test_auto",
            value="Administrators can test the exact spontaneous-post path while bypassing chance and quiet hours.",
            inline=False,
        )
        embed.add_field(
            name="Spontaneous appearances",
            value=(
                "Between 9:00 AM and 9:00 PM Eastern, Riker may post a configured "
                "quote or a clearly labeled original Riker-style remark."
            ),
            inline=False,
        )
        embed.set_footer(text="Try /riker status if a feature is unavailable.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="quote", description="Get a random Riker quote.")
    async def quote(self, interaction: discord.Interaction) -> None:
        item = choose_quote(riker_state.recent_quote_ids)
        if not item:
            await interaction.response.send_message("No quotes are configured yet. Add some to quotes.json.", ephemeral=True)
            return
        await interaction.response.send_message(embed=quote_embed(item))
        record_quote_used(item)

    @app_commands.command(name="advice", description="Ask Commander Riker for his take on a situation.")
    @app_commands.describe(question="What do you want the Commander to weigh in on?")
    async def advice(self, interaction: discord.Interaction, question: str) -> None:
        if not self.client.openai:
            await interaction.response.send_message("AI mode is disabled. Add OPENAI_API_KEY to enable /riker advice.", ephemeral=True)
            return
        now = time.monotonic()
        user_id = interaction.user.id
        last_used = self.client.advice_last_used.get(user_id)
        if last_used is not None and RIKER_ADVICE_COOLDOWN_SECONDS > 0:
            remaining = RIKER_ADVICE_COOLDOWN_SECONDS - (now - last_used)
            if remaining > 0:
                seconds = max(1, int(remaining + 0.999))
                await interaction.response.send_message(
                    f"Easy, Lieutenant. Give me {seconds} more second{'s' if seconds != 1 else ''} before the next briefing.",
                    ephemeral=True,
                )
                return
        self.client.advice_last_used[user_id] = now
        await interaction.response.defer(thinking=True)
        try:
            response = await self.client.openai.responses.create(
                model=OPENAI_MODEL,
                instructions=RIKER_PERSONA,
                input=f"Discord user {interaction.user.display_name} asks:\n{question}\n\nReply directly to that user.",
                max_output_tokens=220,
            )
            text = (response.output_text or "").strip() or "I'm afraid the computer has declined to cooperate."
        except Exception:
            log.exception("OpenAI request failed")
            text = "The computer appears to be having a moment. Ask me again after Engineering has had a look."
        await interaction.followup.send(text[:1900])

    @app_commands.command(name="test_auto", description="Test Riker's real spontaneous-post path now.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test_auto(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await send_spontaneous_quote(self.client)
        destination = f"#{result.channel_name} (`{result.channel_id}`)" if result.channel_id else "no channel"
        icon = "✅" if result.success else "❌"
        outcome = "succeeded" if result.success else "failed"
        await interaction.followup.send(
            f"{icon} Automatic-post test {outcome} for {destination}: {result.reason}", ephemeral=True
        )

    @app_commands.command(name="status", description="See detailed RikerBot diagnostics.")
    async def status(self, interaction: discord.Interaction) -> None:
        lines = [
            "**Commander Riker status**",
            f"• Scheduler running: {'yes' if riker_quote_scheduler.is_running() else 'no'}",
            f"• Base quote chance: {RIKER_QUOTE_CHANCE:.0%} per eligible hour",
            "• Posting hours: 9:00 AM–9:00 PM Eastern",
            f"• Generated remark chance: {RIKER_GENERATED_REMARK_CHANCE:.0%}",
            "• Target channel IDs: " + (", ".join(str(value) for value in RIKER_CHANNEL_IDS) or "none"),
        ]
        for channel_id in RIKER_CHANNEL_IDS:
            channel, error = await resolve_riker_channel(self.client, channel_id)
            if channel is None:
                lines.append(f"  ◦ `{channel_id}`: {error}")
                continue
            permissions = inspect_channel_permissions(self.client, channel)
            lines.append(
                f"  ◦ #{getattr(channel, 'name', channel_id)} (`{channel_id}`): "
                f"view={format_permission(permissions['view_channel'])}, "
                f"send={format_permission(permissions['send_messages'])}, "
                f"embeds={format_permission(permissions['embed_links'])}"
            )
        lines.extend(
            [
                f"• AI advice: {'enabled' if self.client.openai else 'disabled'}",
                f"• Advice model: {OPENAI_MODEL}",
                f"• Advice cooldown: {RIKER_ADVICE_COOLDOWN_SECONDS}s per user",
                "• Last spontaneous post: " + (riker_state.last_spontaneous_post or "never recorded"),
                f"• Recent quote history: {len(riker_state.recent_quote_ids)}/{RIKER_RECENT_QUOTE_HISTORY_SIZE}",
            ]
        )
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@tasks.loop(hours=1)
async def riker_quote_scheduler() -> None:
    current = datetime.now(RIKER_TIMEZONE)
    if not RIKER_CHANNEL_IDS:
        log.info("Scheduler tick %s skipped: no configured channels", current.isoformat())
        return
    if not is_within_posting_hours(current):
        log.info("Scheduler tick %s skipped: quiet hours", current.isoformat())
        return
    threshold = effective_quote_chance(
        current, RIKER_QUOTE_CHANCE, parse_state_time(riker_state.last_spontaneous_post)
    )
    roll = random.random()
    passed = roll <= threshold
    log.info(
        "Eligible scheduler tick eastern=%s roll=%.4f threshold=%.4f passed=%s",
        current.isoformat(), roll, threshold, passed,
    )
    if not passed:
        log.info("Spontaneous post skipped: probability roll did not pass")
        return
    result = await send_spontaneous_quote(bot)
    if result.success:
        log.info(
            "Spontaneous post sent channel_id=%s channel_name=%s kind=%s",
            result.channel_id, result.channel_name, result.content_kind,
        )
    else:
        log.error(
            "Spontaneous post failed channel_id=%s channel_name=%s reason=%s",
            result.channel_id, result.channel_name, result.reason,
        )


@riker_quote_scheduler.before_loop
async def before_riker_quote_scheduler() -> None:
    await bot.wait_until_ready()


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
