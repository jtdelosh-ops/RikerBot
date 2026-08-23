# Commander Riker Discord Bot

A small Python Discord bot that:

- periodically posts a random short Commander Riker quote in one of several approved channels
- observes quiet hours and only posts scheduled quotes from 9:00 AM to 9:00 PM Eastern
- supports `/riker quote`
- supports `/riker advice <question>` when an OpenAI API key is configured
- supports `/riker status`
- supports `/riker help`
- supports administrator diagnostics with `/riker test_auto`
- avoids recently used quotes and persists lightweight posting state locally
- can occasionally post clearly labeled, AI-generated original remarks
- does **not** read ordinary server messages
- keeps the real quote list in a simple `quotes.json` file

The AI personality creates new dialogue inspired by Riker's broad character traits. It is instructed not to reproduce Star Trek scripts or claim generated dialogue is a real quote.

See [CHANGELOG.md](CHANGELOG.md) for a dated summary of project changes.

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

RIKER_QUOTE_CHANCE=0.70
RIKER_GENERATED_REMARK_CHANCE=0.20
RIKER_RECENT_QUOTE_HISTORY_SIZE=10
RIKER_ADVICE_COOLDOWN_SECONDS=30

OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.6-luna
```

### Quote frequency

The scheduler checks once per hour.

Before rolling the random posting chance, it checks the current time in
`America/New_York`. Scheduled posts are allowed beginning at 9:00 AM and stop
at 9:00 PM (the 9:00 PM boundary is excluded). Daylight saving time is handled
automatically. User-invoked slash commands remain available during quiet hours.

`RIKER_QUOTE_CHANCE=0.70` means Riker has a 70% chance of posting during each eligible hourly check.

When an appearance happens, the bot chooses one channel at random from `RIKER_CHANNEL_IDS`. This is an allow-list: Riker will not post scheduled quotes anywhere else.

Examples:

- `0.10` -> about one every 10 hours on average
- `0.20` -> about one every 5 eligible hours on average
- `0.70` -> a post during 70% of eligible hours
- `0.50` -> about one every 2 hours on average
- `1.00` -> every hour

It remains random; those are averages, not fixed intervals.

The effective chance is reduced from 9–11 AM, normal during the day, and
slightly increased after 5 PM. It is also halved when Riker posted within the
last two hours. Quiet hours always take precedence.

`RIKER_GENERATED_REMARK_CHANCE` controls how often a successful appearance
tries to generate a short original remark. Static quotes remain the default,
and any missing or failed AI request falls back to a static quote.

`RIKER_RECENT_QUOTE_HISTORY_SIZE` controls how many recently used quote texts
are avoided. History and the last successful spontaneous-post time are stored
in the ignored local `riker_state.json` file.


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

### `/riker help`

Shows a private, in-Discord guide to all RikerBot commands, scheduled posting
hours, and where slash commands can be used.

### `/riker quote`

Posts a random configured real quote.

### `/riker advice question:...`

Asks the AI personality for Riker-flavored advice.

Example:

```text
/riker advice question:Should I order another pizza?
```

### `/riker status`

Shows scheduler state, configured chance and hours, target channel names and
IDs, per-channel Discord permissions, AI settings, and recent posting state.

### `/riker test_auto`

Server administrators can bypass probability and quiet hours to exercise the
exact same channel resolution, permission checks, embed construction, and
`channel.send(...)` call used by the hourly scheduler. The result is private
and reports actionable Discord errors such as `50013 Missing Permissions`.

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

### Optional: load secrets from 1Password

The 1Password integration is optional. Users who do not use 1Password should
leave `.env.op` absent and continue storing their credentials in the ignored
local `.env` file normally. The standard launcher behavior remains unchanged
for those users, and GitHub CLI is not required.

On Windows, users who have 1Password can inject RikerBot's secrets at runtime
instead of storing plaintext credentials in `.env`:

1. Install and sign in to the 1Password desktop app and 1Password CLI.
2. In 1Password, enable **Settings > Developer > Integrate with 1Password CLI**.
3. Copy `.env.op.example` to `.env.op`.
4. Replace the example `op://` URIs with the references for the Discord token
   and OpenAI API key fields in your 1Password items.
5. Start the bot with `run_windows.bat` and authorize 1Password when prompted.

`.env.op` is ignored by Git and should contain references rather than plaintext
secrets. Non-secret settings such as channel IDs and quote frequency remain in
`.env`. If `.env.op` exists but 1Password CLI is unavailable, the launcher
prints a clear explanation and stops safely; remove `.env.op` to return to the
standard `.env` workflow.

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
