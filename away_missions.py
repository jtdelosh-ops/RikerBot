"""Short, local adventures: one public message and no AI requests."""
import asyncio
import logging
import random

import discord


MISSIONS = (
    (
        "An Unexpected Booking",
        "A distress signal leads to an abandoned station. Behind a sealed door, "
        "something is playing jazz. Riker: ‘I’m willing to call this a promising start.’",
        (
            ("Override the door", "You rescue a scientist locked out by their own security system. The jazz was the hold music.", "‘A successful rescue. We’ll leave the customer satisfaction survey unanswered.’"),
            ("Scan the vents", "You find a maintenance drone rehearsing for its audition. It opens the door in exchange for an honest review.", "‘Excellent engineering. Delicate music criticism.’"),
            ("Play along", "The caretaker AI admits you as the scheduled entertainment. One scientist rescued; three additional nights booked.", "‘We’ll discuss your contractual obligations aboard the ship.’"),
        ),
    ),
    (
        "A Very Reasonable Offer",
        "A Ferengi claims he has purchased the observation lounge. Riker: "
        "‘He’s already charging admission to look out the window. Your recommendation?’",
        (
            ("Negotiate", "You trade exclusive naming rights to a cupboard for the lounge. The cupboard now has a velvet rope.", "‘A small price for keeping the chairs.’"),
            ("Challenge him to poker", "You win the lounge back. Unfortunately, your winnings include his cousin’s experimental snack business.", "‘Check the cargo manifest before opening anything that crunches.’"),
            ("Read the contract", "His deed covers the lounge in a discontinued holodeck simulation. He requests validation for parking.", "‘An outstanding application of reading the second page.’"),
        ),
    ),
    (
        "Diplomatic Duck",
        "The visiting ambassador’s translator insists every sentence means ‘bring me a duck.’ "
        "Riker: ‘Let’s resolve this before the formal dinner.’",
        (
            ("Repair the translator", "You remove a novelty language pack. The ambassador was asking for directions to the library.", "‘Relations restored. Keep the duck on standby.’"),
            ("Replicate a duck", "The ambassador accepts the rubber duck as a ceremonial gift. Your delegation receives an invitation to a bath festival.", "‘Pack the dress uniforms. And something waterproof.’"),
            ("Try charades", "An elaborate exchange of gestures establishes friendship and accidentally signs you up for the talent show.", "‘First contact was easier before interpretive dance.’"),
        ),
    ),
)


class AwayMissionView(discord.ui.View):
    def __init__(self, mission=None):
        super().__init__(timeout=180)
        self.mission = mission if mission is not None else random.choice(MISSIONS)
        self.message = None
        self.finished = False
        self.lock = asyncio.Lock()
        for index, (label, _, _) in enumerate(self.mission[2]):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

            async def choose(interaction, choice=index):
                await self.resolve(interaction, choice)

            button.callback = choose
            self.add_item(button)

    def briefing(self):
        embed = discord.Embed(title=f"Away Mission — {self.mission[0]}", description=self.mission[1], color=0xB79852)
        embed.set_footer(text="Anyone can choose • First choice wins • Expires after 3 minutes • Original fiction")
        return embed

    async def resolve(self, interaction, choice):
        async with self.lock:
            if self.finished:
                await interaction.response.send_message("This mission has already ended.", ephemeral=True)
                return
            label, outcome, remark = self.mission[2][choice]
            embed = discord.Embed(title=f"Mission Complete — {self.mission[0]}", description=f"**Decision: {label}**\n\n{outcome}\n\n**Riker:** {remark}", color=0xB79852)
            embed.set_footer(text="Original fiction • Start another with /riker awaymission")
            await interaction.response.edit_message(embed=embed, view=None)
            self.finished = True
            self.stop()

    async def on_timeout(self):
        async with self.lock:
            if self.finished:
                return
            self.finished = True
            if self.message is not None:
                embed = self.briefing()
                embed.set_footer(text="Mission expired • Start another with /riker awaymission")
                try:
                    await self.message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    logging.getLogger("riker-bot").debug("Could not clear expired mission buttons", exc_info=True)
