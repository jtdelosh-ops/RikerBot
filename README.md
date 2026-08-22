# Commander Riker Discord Bot

A small Python Discord bot that:

- periodically posts a random short Commander Riker quote in one of several approved channels
- supports `/riker quote`
- supports `/riker advice <question>` when an OpenAI API key is configured
- supports `/riker status`
- does **not** read ordinary server messages
- keeps the real quote list in a simple `quotes.json` file

The AI personality creates new dialogue inspired by Riker's broad character traits. It is instructed not to reproduce Star Trek scripts or claim generated dialogue is a real quote.

## 1. Requirements

- Python 3.11+ recommended
- A Discord account/server where you can add an app
- Optional: an OpenAI API key for `/riker advice`

## 2. Create the Discord bot

1. Open the Discord Developer Portal:
   https://discord.com/developers/applications
2. Click **New Application** and name it something like `Commander Riker`.
3. Open **Bot** and create/configure the bot.
4. Copy/reset the bot token.
5. Put that token in `.env` as `DISCORD_TOKEN`.
6. You do **not** need the Message Content intent for this version.

### Invite it to your server

Under the application's installation/OAuth settings, generate an install/invite with:

Scopes:
- `bot`
- `applications.commands`

Useful bot permissions:
- View Channels
- Send Messages
- Embed Links
- Read Message History

Open the generated invite and add the bot to your server.

## 3. Get your IDs

In Discord:

1. Settings -> Advanced -> enable **Developer Mode**.
2. Right-click your server -> **Copy Server ID**.
3. Right-click each channel where Riker is allowed to appear -> **Copy Channel ID**.

Put them in `.env` as a comma-separated list:

```env
RIKER_CHANNEL_IDS=123456789012345678,234567890123456789,345678901234567890
DISCORD_GUILD_ID=987654321098765432
```

Riker randomly chooses one of those approved channels each time the scheduler decides he should appear.

For compatibility, the old single-channel setting still works if `RIKER_CHANNEL_IDS` is blank:

```env
RIKER_CHANNEL_ID=123456789012345678
```

`DISCORD_GUILD_ID` is recommended during development because guild-scoped slash-command changes appear quickly.

## 4. Windows setup

Double-click:

```text
setup_windows.bat
```

It creates `.venv`, installs the Python packages, and creates `.env` if needed.

Then edit `.env`.

Start the bot with:

```text
run_windows.bat
```

Or from PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python bot.py
```

## 5. macOS / Linux setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## 6. Configuration

Example:

```env
DISCORD_TOKEN=your_discord_token
RIKER_CHANNEL_IDS=123456789012345678,234567890123456789
DISCORD_GUILD_ID=987654321098765432

RIKER_QUOTE_CHANCE=0.20
RIKER_ADVICE_COOLDOWN_SECONDS=30

OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.6-luna
```

### Quote frequency

The scheduler checks once per hour.

`RIKER_QUOTE_CHANCE=0.20` means Riker has a 20% chance of posting each hour, so over a long period that averages around one appearance per five hours.

When an appearance happens, the bot chooses one channel at random from `RIKER_CHANNEL_IDS`. This is an allow-list: Riker will not post scheduled quotes anywhere else.

Examples:

- `0.10` -> about one every 10 hours on average
- `0.20` -> about one every 5 hours on average
- `0.50` -> about one every 2 hours on average
- `1.00` -> every hour

It remains random; those are averages, not fixed intervals.


### AI advice cooldown

`/riker advice` has a per-user cooldown to prevent accidental or intentional API spam.

```env
RIKER_ADVICE_COOLDOWN_SECONDS=30
```

With the default `30`, each Discord user can make at most one accepted AI advice request every 30 seconds. The cooldown is tracked separately for each user.

Set it higher if you want stronger cost protection, for example:

```env
RIKER_ADVICE_COOLDOWN_SECONDS=60
```


## 7. Commands

### `/riker quote`

Posts a random configured real quote.

### `/riker advice question:...`

Asks the AI personality for Riker-flavored advice.

Example:

```text
/riker advice question:Should I order another pizza?
```

### `/riker status`

Shows whether the scheduled quote system and optional AI system are enabled.

## 8. Add more quotes

Edit `quotes.json`:

```json
[
  {
    "quote": "Your short quote here.",
    "source": "TNG — Episode Name"
  }
]
```

Keep quotes short and verify the wording/source yourself before adding them. Restarting is not required for quote edits; the file is reloaded whenever a quote is selected.

## 9. Keep secrets out of Git

`.env` is included in `.gitignore`.

Never commit:
- your Discord bot token
- your OpenAI API key

If you accidentally expose a Discord token, reset it in the Developer Portal.

## 10. How it works

```text
Discord
   |
   v
bot.py
   |
   +-- /riker quote ------> quotes.json
   |
   +-- hourly scheduler --> random chance --> quotes.json --> configured channel
   |
   +-- /riker advice -----> OpenAI Responses API (optional)
```

## Good next upgrades

The natural next version would add one or more of:

- weighted roaming so some channels are more likely than others
- Riker occasionally interjecting into normal conversation
- per-user Starfleet ranks
- `/riker evaluate @user`
- rare "Commander Riker has entered Ten Forward" events
- a cooldown so the same quote cannot repeat too soon
- an admin command to change quote frequency without restarting
- persistent conversation memory for `/riker advice`
