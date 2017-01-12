import discord
from discord.ext import commands
from .utils import checks
import time


class SlowMode:
    def __init__(self, bot):
        self.bot = bot
        self.lastTimeTalkingMap = {}
        self.slowDuration = {}
        self.bot.add_listener(self.limiter, "on_message")

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, delay: str):
        """Sets slowmode duration in this channel.
        """
        if not delay.isdigit():
            await self.bot.say("You must provide a valid number.")
            return
        self.slowDuration[ctx.message.channel] = int(delay)
        await self.bot.say("This channel is now in :snail: mode. ({} seconds).".format(delay))

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowoff(self, ctx):
        """Disables slowmode in this channel.
        """
        self.slowDuration[ctx.message.channel] = 0
        await self.bot.say("This channel is no longer in :snail: mode.")

    async def limiter(self, message: discord.Message):
        if self.can_bypass(message):
            return
        slow_in_this_channel = self.slowDuration.get(message.channel, 0)
        if slow_in_this_channel == 0:
            return
        user_and_channel = (message.channel, message.author)
        talking_now = int(time.time())
        if (talking_now - self.lastTimeTalkingMap.get(user_and_channel, 0)) <= slow_in_this_channel:
            await self.bot.delete_message(message)
        self.lastTimeTalkingMap[user_and_channel] = talking_now

    def can_bypass(self, msg):
        server = msg.server
        mod_role = self.bot.settings.get_server_mod(server).lower()
        admin_role = self.bot.settings.get_server_admin(server).lower()
        return self.role_or_permissions(msg, lambda r: r.name.lower() in (mod_role, admin_role), manage_messages=True)

    def role_or_permissions(self, msg, check, **perms):
        if self.check_permissions(msg, perms):
            return True

        ch = msg.channel
        author = msg.author
        if ch.is_private:
            return False

        role = discord.utils.find(check, author.roles)
        return role is not None

    def check_permissions(self, msg, perms):
        if msg.author.id == self.bot.settings.owner:
            return True
        elif not perms:
            return False

        ch = msg.channel
        author = msg.author
        resolved = ch.permissions_for(author)
        return all(getattr(resolved, name, None) == value for name, value in perms.items())


def setup(bot):
    bot.add_cog(SlowMode(bot))
