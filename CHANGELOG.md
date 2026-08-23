# Changelog

Notable changes to RikerBot are recorded here. The project does not currently
use numbered releases, so entries are grouped by date.

## Unreleased

### Added

- Optional Windows launcher support for injecting `DISCORD_TOKEN` and
  `OPENAI_API_KEY` from 1Password CLI secret references.
- A safe `.env.op.example` template; real `.env.op` files remain ignored.

### Changed

- Raised the configurable `/riker advice` response ceiling from 220 to 500
  tokens while strengthening the concise, playful Riker-style guidance.
- Changed complex advice requests to receive a short topical reaction instead
  of a long calculation or program, with one simplified retry for empty replies.

### Documentation

- Clarified that 1Password CLI is not required and users without it should
  leave `.env.op` absent and continue using the standard `.env` workflow.

## 2026-08-23 — Diagnostics and livelier appearances

### Added

- `/riker test_auto` for administrators to exercise the same channel lookup,
  permission checks, embed construction, and `channel.send(...)` path used by
  scheduled appearances.
- Actionable Discord permission diagnostics, including explicit reporting for
  `50013 Missing Permissions` errors.
- Detailed `/riker status` output covering scheduler state, posting settings,
  target channel resolution, channel permissions, AI configuration, and recent
  spontaneous-post state.
- Persistent local state in `riker_state.json` for recent quote history and the
  last successful spontaneous post time.
- Anti-repeat quote selection with configurable recent-history length.
- Optional, clearly labeled AI-generated spontaneous remarks with automatic
  fallback to static quotes.
- Time-of-day cadence adjustments and a cooldown effect after a recent post.
- Scheduler logs containing Eastern time, random roll, effective threshold,
  selected destination, result, and specific failure or skip reason.
- Tests for quiet hours, cadence, anti-repeat behavior, state persistence,
  permission reporting, shared automatic sending, and Discord error `50013`.

### Configuration

- Added `RIKER_GENERATED_REMARK_CHANCE` with a default of `0.20`.
- Added `RIKER_RECENT_QUOTE_HISTORY_SIZE` with a default of `10`.

### Changed

- `/riker help` now describes original spontaneous remarks, `/riker test_auto`,
  and the expanded status diagnostics.
- Static quote selection now avoids recently used content when possible.
- The hourly scheduler now varies its effective probability while continuing
  to enforce strict 9:00 PM–9:00 AM Eastern quiet hours.

## 2026-08-22 — Initial RikerBot

### Added

- Discord slash commands for quotes, AI-powered advice, status, and help.
- Hourly spontaneous quote scheduling across approved channels.
- Strict 9:00 AM–9:00 PM Eastern posting hours.
- Configurable posting probability and per-user advice cooldown.
- JSON-backed quote library and Python 3.10–3.13 GitHub Actions test matrix.
