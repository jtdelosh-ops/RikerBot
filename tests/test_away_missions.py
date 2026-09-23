import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
from away_missions import AwayMissionView, MISSIONS


def interaction():
    return SimpleNamespace(
        channel_id=42,
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        original_response=AsyncMock(),
    )


class MissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_branch_resolves_in_original_message(self):
        for mission in MISSIONS:
            for index in range(3):
                view = AwayMissionView(mission)
                event = interaction()
                await view.children[index].callback(event)
                event.response.edit_message.assert_awaited_once()
                payload = event.response.edit_message.call_args.kwargs
                self.assertIsNone(payload['view'])
                self.assertIn(mission[2][index][1], payload['embed'].description)
                event.response.send_message.assert_not_awaited()
                self.assertTrue(view.finished)

    async def test_simultaneous_choices_only_resolve_once(self):
        view = AwayMissionView()
        first, second = interaction(), interaction()
        await asyncio.gather(view.resolve(first, 0), view.resolve(second, 1))
        self.assertEqual(first.response.edit_message.await_count + second.response.edit_message.await_count, 1)
        second.response.send_message.assert_awaited_once_with("This mission has already ended.", ephemeral=True)

    async def test_timeout_edits_without_sending_and_blocks_choices(self):
        view = AwayMissionView()
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        self.assertIsNone(view.message.edit.call_args.kwargs['view'])
        event = interaction()
        await view.resolve(event, 0)
        event.response.edit_message.assert_not_awaited()
        self.assertTrue(event.response.send_message.call_args.kwargs['ephemeral'])

    async def test_completed_mission_not_overwritten_on_timeout(self):
        view = AwayMissionView()
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.resolve(interaction(), 0)
        await view.on_timeout()
        view.message.edit.assert_not_awaited()

    async def test_command_restricts_channel_and_posts_one_message(self):
        commands = bot.RikerCommands(bot.bot)
        bot.away_mission_last_started.clear()
        denied = interaction()
        with patch.object(bot, 'RIKER_CHANNEL_IDS', []):
            await commands.awaymission.callback(commands, denied)
        self.assertTrue(denied.response.send_message.call_args.kwargs['ephemeral'])
        allowed = interaction()
        with patch.object(bot, 'RIKER_CHANNEL_IDS', [42]):
            await commands.awaymission.callback(commands, allowed)
        allowed.response.send_message.assert_awaited_once()
        view = allowed.response.send_message.call_args.kwargs['view']
        self.assertEqual(view.timeout, 180)
        view.stop()
        again = interaction()
        with patch.object(bot, 'RIKER_CHANNEL_IDS', [42]):
            await commands.awaymission.callback(commands, again)
        again.response.send_message.assert_awaited_once()
        self.assertTrue(again.response.send_message.call_args.kwargs['ephemeral'])
        self.assertIn("away team", again.response.send_message.call_args.args[0])
        bot.away_mission_last_started.clear()
