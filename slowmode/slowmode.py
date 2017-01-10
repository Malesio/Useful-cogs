import discord
from discord.ext import commands
from discord.ext.commands import Bot
from .utils import checks
import time


class SlowMode:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.lastTimeTalkingMap = {}
        self.slowDuration = {}
        self.bot.add_listener(self.limiter, "on_message")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, delay_string: str):
        if not delay_string.isdigit():
            await self.bot.say("You must provide a valid number.")
            return
        self.slowDuration[ctx.message.channel] = int(delay_string)
        await self.bot.say("This channel is now in :snail: mode. ({} seconds).".format(delay_string))

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowoff(self, ctx):
        self.slowDuration[ctx.message.channel] = 0
        await self.bot.say("This channel is no longer in :snail: mode.")

    async def limiter(self, message: discord.Message):
        if checks.mod_or_permissions(manage_messages=True):
            return
        slow_in_this_channel = self.slowDuration.get(message.channel, 0)
        if slow_in_this_channel == 0:
            return
        user_and_channel = (message.channel, message.author)
        talking_now = int(time.time())
        if (talking_now - self.lastTimeTalkingMap.get(user_and_channel, 0)) <= slow_in_this_channel:
            await self.bot.delete_message(message)
        self.lastTimeTalkingMap[user_and_channel] = talking_now


def setup(bot: Bot):
    bot.add_cog(SlowMode(bot))
