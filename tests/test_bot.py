from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import bot


class PostingHoursTests(unittest.TestCase):
    def test_posting_boundaries(self) -> None:
        self.assertFalse(bot.is_within_posting_hours(datetime(2026, 1, 1, 8, 59)))
        self.assertTrue(bot.is_within_posting_hours(datetime(2026, 1, 1, 9, 0)))
        self.assertTrue(bot.is_within_posting_hours(datetime(2026, 1, 1, 20, 59)))
        self.assertFalse(bot.is_within_posting_hours(datetime(2026, 1, 1, 21, 0)))

    def test_aware_datetime_is_converted_to_eastern(self) -> None:
        self.assertTrue(
            bot.is_within_posting_hours(
                datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
            )
        )


class CadenceTests(unittest.TestCase):
    def test_early_morning_is_lower_and_evening_is_higher(self) -> None:
        morning = bot.effective_quote_chance(datetime(2026, 1, 1, 9), 0.50)
        daytime = bot.effective_quote_chance(datetime(2026, 1, 1, 13), 0.50)
        evening = bot.effective_quote_chance(datetime(2026, 1, 1, 18), 0.50)
        self.assertLess(morning, daytime)
        self.assertGreater(evening, daytime)

    def test_recent_post_reduces_probability(self) -> None:
        now = datetime(2026, 1, 1, 13, tzinfo=bot.RIKER_TIMEZONE)
        normal = bot.effective_quote_chance(now, 0.70)
        recent = bot.effective_quote_chance(now, 0.70, now - timedelta(hours=1))
        self.assertEqual(recent, normal * 0.5)


class QuoteSelectionTests(unittest.TestCase):
    def test_avoids_recent_quotes(self) -> None:
        quotes = [
            {"quote": "Alpha", "source": "test"},
            {"quote": "Bravo", "source": "test"},
        ]
        with patch.object(bot, "load_quotes", return_value=quotes):
            selected = bot.choose_quote([bot.quote_identity(quotes[0])])
        self.assertEqual(selected, quotes[1])

    def test_small_library_degrades_gracefully(self) -> None:
        only_quote = {"quote": "Alpha", "source": "test"}
        with patch.object(bot, "load_quotes", return_value=[only_quote]):
            selected = bot.choose_quote([bot.quote_identity(only_quote)])
        self.assertEqual(selected, only_quote)

    def test_real_quote_library_loads(self) -> None:
        quotes = bot.load_quotes()
        self.assertGreaterEqual(len(quotes), 24)
        self.assertTrue(all(item["quote"] for item in quotes))


class StateTests(unittest.TestCase):
    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            expected = bot.RikerState(["alpha", "bravo"], "2026-01-01T12:00:00-05:00")
            bot.save_state(expected, path)
            self.assertEqual(bot.load_state(path), expected)

    def test_missing_and_corrupt_state_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertEqual(bot.load_state(path), bot.RikerState())
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(bot.load_state(path), bot.RikerState())


class PermissionTests(unittest.TestCase):
    def test_permission_failure_names_missing_permissions(self) -> None:
        reason = bot.permission_failure_reason(
            {"view_channel": True, "send_messages": False, "embed_links": False}
        )
        self.assertEqual(reason, "Missing Discord permission(s): Send Messages, Embed Links")


class AdviceConfigurationTests(unittest.TestCase):
    def test_advice_has_moderate_output_ceiling_and_concise_persona(self) -> None:
        self.assertEqual(bot.RIKER_ADVICE_MAX_OUTPUT_TOKENS, 500)
        self.assertIn("never produce a wall of text", bot.RIKER_PERSONA)
        self.assertIn("slightly flowery science-fiction language", bot.RIKER_PERSONA)
        self.assertIn("you do not need to complete complicated calculations", bot.RIKER_PERSONA)


class AdviceResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_advice_retries_with_a_simpler_short_prompt(self) -> None:
        openai = SimpleNamespace(
            responses=SimpleNamespace(
                create=AsyncMock(
                    side_effect=[
                        SimpleNamespace(output_text=""),
                        SimpleNamespace(output_text="Tea first, Lieutenant. Pi can wait until Engineering finishes its diagnostics."),
                    ]
                )
            )
        )
        client = SimpleNamespace(openai=openai, advice_last_used={})
        commands = bot.RikerCommands(client)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, display_name="Data"),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await bot.RikerCommands.advice.callback(
            commands,
            interaction,
            "Make tea and calculate 200 digits of pi in COBOL.",
        )

        self.assertEqual(openai.responses.create.await_count, 2)
        retry = openai.responses.create.await_args_list[1].kwargs
        self.assertIn("do not calculate it or write code", retry["input"])
        interaction.followup.send.assert_awaited_once_with(
            "Tea first, Lieutenant. Pi can wait until Engineering finishes its diagnostics."
        )

    async def test_double_empty_advice_uses_in_character_fallback(self) -> None:
        openai = SimpleNamespace(
            responses=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(output_text=""))
            )
        )
        client = SimpleNamespace(openai=openai, advice_last_used={})
        commands = bot.RikerCommands(client)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=43, display_name="Geordi"),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await bot.RikerCommands.advice.callback(commands, interaction, "Calculate pi.")

        self.assertEqual(openai.responses.create.await_count, 2)
        sent = interaction.followup.send.await_args.args[0]
        self.assertNotIn("declined to cooperate", sent)
        self.assertIn("bridge shift", sent)


class AutomaticSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_test_auto_delegates_to_shared_send_helper(self) -> None:
        client = MagicMock()
        commands = bot.RikerCommands(client)
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        expected = bot.SendResult(True, "Sent a static quote.", 123, "ten-forward")

        with patch.object(
            bot, "send_spontaneous_quote", AsyncMock(return_value=expected)
        ) as shared_send:
            await bot.RikerCommands.test_auto.callback(commands, interaction)

        shared_send.assert_awaited_once_with(client)
        interaction.followup.send.assert_awaited_once()

    async def test_shared_auto_path_calls_channel_send(self) -> None:
        """This is the same channel.send path used by scheduler and test_auto."""
        channel = SimpleNamespace(name="ten-forward", send=AsyncMock())
        client = MagicMock()
        quote = {"quote": "Steady as she goes.", "source": "test"}
        with (
            patch.object(bot, "resolve_riker_channel", AsyncMock(return_value=(channel, None))),
            patch.object(
                bot,
                "inspect_channel_permissions",
                return_value={
                    "view_channel": True,
                    "send_messages": True,
                    "embed_links": True,
                },
            ),
            patch.object(bot, "choose_quote", return_value=quote),
            patch.object(bot, "record_quote_used"),
            patch.object(bot, "save_state"),
        ):
            result = await bot.send_spontaneous_quote(
                client, channel_id=123, generated_roll=1.0
            )

        self.assertTrue(result.success)
        channel.send.assert_awaited_once()
        self.assertIsInstance(channel.send.await_args.kwargs["embed"], discord.Embed)

    async def test_missing_permissions_50013_is_reported(self) -> None:
        response = MagicMock(status=403, reason="Forbidden")
        error = discord.Forbidden(
            response, {"code": 50013, "message": "Missing Permissions"}
        )
        channel = SimpleNamespace(name="ten-forward", send=AsyncMock(side_effect=error))
        client = MagicMock()
        with (
            patch.object(bot, "resolve_riker_channel", AsyncMock(return_value=(channel, None))),
            patch.object(
                bot,
                "inspect_channel_permissions",
                return_value={
                    "view_channel": True,
                    "send_messages": True,
                    "embed_links": True,
                },
            ),
            patch.object(
                bot, "choose_quote", return_value={"quote": "Alpha", "source": "test"}
            ),
        ):
            result = await bot.send_spontaneous_quote(
                client, channel_id=123, generated_roll=1.0
            )

        self.assertFalse(result.success)
        self.assertIn("Missing Permissions", result.reason)
        self.assertIn("50013", result.reason)
        channel.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
