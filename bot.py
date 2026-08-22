from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
QUOTES_PATH = BASE_DIR / "quotes.json"

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0") or 0)

def parse_channel_ids() -> list[int]:
    """Load approved text-channel IDs from .env.

    Preferred:
        RIKER_CHANNEL_IDS=111,222,333

    Backwards compatible:
        RIKER_CHANNEL_ID=111
    """
    raw_multi = os.getenv("RIKER_CHANNEL_IDS", "").strip()
    raw_single = os.getenv("RIKER_CHANNEL_ID", "").strip()

    raw = raw_multi or raw_single
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
            log.warning("Ignoring invalid channel ID in .env: %r", value)

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(channel_ids))


RIKER_CHANNEL_IDS = parse_channel_ids()

# Once per scheduler tick, Riker has this probability of posting.
# 0.20 with a 60-minute tick means ~1 appearance every 5 hours on average.
RIKER_QUOTE_CHANCE = max(
    0.0, min(1.0, float(os.getenv("RIKER_QUOTE_CHANCE", "0.20")))
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()

# Per-user cooldown for AI-powered /riker advice requests.
RIKER_ADVICE_COOLDOWN_SECONDS = max(
    0, int(os.getenv("RIKER_ADVICE_COOLDOWN_SECONDS", "30") or 30)
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("riker-bot")


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


def choose_quote() -> dict[str, str] | None:
    quotes = load_quotes()
    return random.choice(quotes) if quotes else None


def quote_embed(item: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(
        description=f'“{item["quote"]}”',
        title="Commander Riker",
    )
    if item.get("source"):
        embed.set_footer(text=item["source"])
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
        # This version does not read ordinary server messages.
        intents.message_content = False

        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        )
        self.advice_last_used: dict[int, float] = {}

    async def setup_hook(self) -> None:
        self.tree.add_command(RikerCommands(self))

        # Guild syncing is much faster while developing. If no guild ID is supplied,
        # commands are registered globally instead.
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
            log.info(
                "Riker roaming enabled across %d approved channel(s).",
                len(RIKER_CHANNEL_IDS),
            )
        else:
            log.warning(
                "RIKER_CHANNEL_IDS is not set; scheduled quotes are disabled. "
                "Slash commands will still work."
            )

    async def on_ready(self) -> None:
        if self.user:
            log.info("Logged in as %s (%s)", self.user, self.user.id)


bot = RikerBot()


class RikerCommands(app_commands.Group):
    def __init__(self, client: RikerBot) -> None:
        super().__init__(name="riker", description="Commander Riker has the conn.")
        self.client = client

    @app_commands.command(name="quote", description="Get a random Riker quote.")
    async def quote(self, interaction: discord.Interaction) -> None:
        item = choose_quote()
        if not item:
            await interaction.response.send_message(
                "No quotes are configured yet. Add some to quotes.json.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=quote_embed(item))

    @app_commands.command(
        name="advice",
        description="Ask Commander Riker for his take on a situation.",
    )
    @app_commands.describe(question="What do you want the Commander to weigh in on?")
    async def advice(self, interaction: discord.Interaction, question: str) -> None:
        if not self.client.openai:
            await interaction.response.send_message(
                "AI mode is disabled. Add OPENAI_API_KEY to .env to enable /riker advice.",
                ephemeral=True,
            )
            return

        # Per-user cooldown prevents one person from repeatedly spending API credits.
        now = time.monotonic()
        user_id = interaction.user.id
        last_used = self.client.advice_last_used.get(user_id)

        if last_used is not None and RIKER_ADVICE_COOLDOWN_SECONDS > 0:
            elapsed = now - last_used
            remaining = RIKER_ADVICE_COOLDOWN_SECONDS - elapsed
            if remaining > 0:
                seconds = max(1, int(remaining + 0.999))
                await interaction.response.send_message(
                    f"Easy, Lieutenant. Give me {seconds} more second"
                    f"{'s' if seconds != 1 else ''} before the next briefing.",
                    ephemeral=True,
                )
                return

        # Start the cooldown when the request is accepted, not after it finishes.
        self.client.advice_last_used[user_id] = now

        await interaction.response.defer(thinking=True)

        try:
            response = await self.client.openai.responses.create(
                model=OPENAI_MODEL,
                instructions=RIKER_PERSONA,
                input=(
                    f"Discord user {interaction.user.display_name} asks:\n"
                    f"{question}\n\n"
                    "Reply directly to that user."
                ),
                max_output_tokens=220,
            )
            text = (response.output_text or "").strip()
            if not text:
                text = "I'm afraid the computer has declined to cooperate."
        except Exception:
            log.exception("OpenAI request failed")
            text = (
                "The computer appears to be having a moment. "
                "Ask me again after Engineering has had a look."
            )

        await interaction.followup.send(text[:1900])

    @app_commands.command(
        name="status",
        description="See whether Riker's automated systems are online.",
    )
    async def status(self, interaction: discord.Interaction) -> None:
        quote_mode = (
            f"online ({RIKER_QUOTE_CHANCE:.0%} chance each hour across "
            f"{len(RIKER_CHANNEL_IDS)} channel(s))"
            if RIKER_CHANNEL_IDS
            else "disabled (no RIKER_CHANNEL_IDS)"
        )
        ai_mode = f"online ({OPENAI_MODEL})" if self.client.openai else "disabled"

        await interaction.response.send_message(
            f"**Commander Riker status**\n"
            f"• Scheduled quotes: {quote_mode}\n"
            f"• AI advice: {ai_mode}\n"
            f"• Advice cooldown: {RIKER_ADVICE_COOLDOWN_SECONDS}s per user",
            ephemeral=True,
        )


@tasks.loop(hours=1)
async def riker_quote_scheduler() -> None:
    if not RIKER_CHANNEL_IDS:
        return

    if random.random() > RIKER_QUOTE_CHANCE:
        log.info("Riker stayed in his ready room this hour.")
        return

    # Pick one approved channel at random each time Riker makes an appearance.
    channel_id = random.choice(RIKER_CHANNEL_IDS)

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.DiscordException:
            log.exception("Could not find configured Riker channel %s", channel_id)
            return

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.error(
            "Configured channel ID %s does not point to a text channel or thread.",
            channel_id,
        )
        return

    item = choose_quote()
    if not item:
        log.warning("No quotes available.")
        return

    try:
        await channel.send(embed=quote_embed(item))
        log.info(
            "Commander Riker made an appearance in #%s (%s).",
            getattr(channel, "name", "unknown"),
            channel_id,
        )
    except discord.DiscordException:
        log.exception("Could not send scheduled quote to channel %s", channel_id)


@riker_quote_scheduler.before_loop
async def before_riker_quote_scheduler() -> None:
    await bot.wait_until_ready()


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token."
        )
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
