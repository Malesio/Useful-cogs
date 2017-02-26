import discord
from discord.ext import commands
from .utils.chat_formatting import *
from .utils import checks
from .utils.dataIO import dataIO
import asyncio
import os
import logging
from time import time

log = logging.getLogger("red.bans")
log.setLevel(logging.INFO)
BANS_DATA_FILE = "data/bans/bans.json"


class BanCase:
    def __init__(self, data=None):
        self.id = data.pop('id')
        self.server = data.pop('server')
        self.name = data.pop('name')
        self.bannedBy = data.pop('bannedBy')
        self.banTimestamp = data.pop('banTimestamp')
        self.duration = data.pop('duration')
        self.reason = data.pop('reason')

    def __lt__(self, other):
        return int(self.banTimestamp) < int(other.banTimestamp)


class AdvancedBans:
    def __init__(self, bot):
        self.bot = bot
        self.bans_data = dataIO.load_json(BANS_DATA_FILE)
        self.queue = asyncio.PriorityQueue(loop=self.bot.loop)
        self.lock = asyncio.Lock()
        self.load_cases()
        self.mod_channel = None

    @staticmethod
    def parse_duration(duration):
        translate = {'d': 86400, 'w': 604800, 'y': 31536000}
        timespec = duration[-1]
        if timespec.lower() not in translate:
            raise ValueError("Invalid suffix. Please provide some of them : {}"
                             .format(", ".join(translate.keys()).rstrip(", ")))
        timeint = int(duration[:-1])
        return timeint * translate.get(timespec)

    def save_bans_data(self):
        dataIO.save_json(BANS_DATA_FILE, self.bans_data)

    def user_already_banned(self, server, user):
        return user.id in self.bans_data[server.id]

    def populate_ban_data(self, server, user, author, duration, *reason):
        self.bans_data[server.id][user.id] = {
            "name": user.name,
            "bannedBy": {
                "name": author.name, "id": author.id
            },
            "duration": duration,
            "banTimestamp": int(time()),
            "reason": " ".join(reason)
        }

        event_dict = self.bans_data[server.id][user.id].copy()
        event_dict["server"] = server.id
        event_dict["id"] = user.id
        case = BanCase(event_dict)
        self.bot.loop.create_task(self.post_case(case))

        self.save_bans_data()

    def load_cases(self):
        for server in self.bans_data:
            for userID, case in self.bans_data[server].items():
                ret = {"server": server, "id": userID}
                ret.update(case)
                new_case = BanCase(ret)
                self.bot.loop.create_task(self.post_case(new_case))

    async def post_case(self, ban_case, future=None):
        if future is None:
            future = ban_case.banTimestamp + ban_case.duration
        await self.queue.put((future, ban_case))
        log.debug("Posted scheduled unban of {} at {}".format(ban_case.name, future))

    async def remove_case(self, user_id, server):
        await self.lock.acquire()
        events_to_queue = []
        while self.queue.qsize() != 0:
            unban_timestamp, event = await self.queue.get()
            if not (user_id == event.id and server.id == event.server):
                events_to_queue.append((unban_timestamp, event))
        for event in events_to_queue:
            await self.queue.put(event)
        self.lock.release()

    async def avert_banned_user(self, server, user, duration: str, *reason):
        suffix_to_unit = {'d': "day", 'w': "week", 'y': "year"}
        time_unit = duration[-1]

        if time_unit.lower() not in suffix_to_unit:
            raise ValueError("Invalid suffix. Please provide some of them : {}"
                             .format(", ".join(suffix_to_unit.keys()).rstrip(", ")))

        time_multiplier = int(duration[:-1])
        duration_string = duration[:-1] + " " + suffix_to_unit[time_unit] + ("s" if time_multiplier != 1 else "")

        await self.bot.send_message(user, "You have been banned on {} for {}. Reason : {}"
                                    .format(server.name, duration_string, " ".join(reason)))

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(ban_members=True)
    async def tempban(self, ctx, user: discord.Member, duration, *reason):
        """Ban a member for certain amount of time, or forever.

        user: The user to ban
        duration: How long the ban will stay, or 'def' to ban forever
        reason: The reason of the ban
        """
        server = ctx.message.server
        mod = ctx.message.author
        channel_logging = self.mod_channel or ctx.message.channel

        await self.bot.delete_message(ctx.message)

        if server.id not in self.bans_data:
            self.bans_data[server.id] = {}

        if self.user_already_banned(server, user):
            await self.bot.send_message(channel_logging, "{} : User already banned.".format(mod.mention))
            return

        try:
            duration_sec = self.parse_duration(duration)
        except ValueError as e:
            await self.bot.send_message(channel_logging, box(e))
            return
        if duration_sec <= 0:
            await self.bot.send_message(channel_logging, "Are you kidding me ? Could you provide some"
                                                         " valid duration {} ?".format(mod.mention))
            return

        if len(reason) == 0:
            await self.bot.send_message(channel_logging, "Please provide a reason for the ban.")
            return

        self.populate_ban_data(server, user, mod, duration_sec, *reason)
        await self.avert_banned_user(server, user, duration, *reason)
        await self.bot.ban(user)
        await self.bot.say("The Ban :hammer: has spoken!")

    def get_user_by_name(self, server, username: str):
        matched_user = [k for k, v in self.bans_data[server.id].items() if v["name"] == username]
        logging.info("Matched : {}".format(matched_user))
        return matched_user[0] if len(matched_user) > 0 else None

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(ban_members=True)
    async def unban(self, ctx, username: str):
        """Unban a user before ban revoke date, or because user was banned forever.
        user: The user to unban
        """
        server = ctx.message.server
        channel_logging = self.mod_channel or ctx.message.channel

        await self.bot.delete_message(ctx.message)

        if server.id not in self.bans_data:
            await self.bot.send_message(channel_logging, "This server is not registered in the ban list.")
            return

        user_id = self.get_user_by_name(server, username)
        if user_id is None:
            await self.bot.send_message(channel_logging, "This user is not tempbanned. "
                                                         "Maybe banned forever, who knows.")
            return
        user = await self.bot.get_user_info(user_id)

        del self.bans_data[server.id][user.id]
        await self.remove_case(user.id, server)
        await self.bot.unban(server, user)
        self.save_bans_data()

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(ban_members=True)
    async def banfetch(self, ctx, username: str):
        """Retrieve the ban log for the given username.

        username: The banned username
        """
        server = ctx.message.server
        channel_logging = self.mod_channel or ctx.message.channel

        await self.bot.delete_message(ctx.message)

        if server.id not in self.bans_data:
            await self.bot.send_message(channel_logging, "{} is not in the ban list.".format(server.name))
            return

        user = self.get_user_by_name(server, username)

        if user is None:
            await self.bot.send_message(channel_logging, "{} is not banned.".format(username))
            return

        user_ban_data = self.bans_data[server.id][user]
        embed = discord.Embed(title="Ban report :hammer:", type="rich")
        embed.add_field(name="User", value=user_ban_data["name"])
        embed.add_field(name="Mod", value=user_ban_data["bannedBy"]["name"])
        embed.add_field(name="Duration", value="{} day(s)".format(int(user_ban_data["duration"]) / 86400))
        embed.add_field(name="Reason", value=user_ban_data["reason"])
        embed.colour = discord.Colour(0xBB271C)
        embed.set_footer(text=ctx.message.author.name)

        await self.bot.send_message(channel_logging, embed=embed)

    @commands.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(ban_members=True)
    async def modchan(self, ctx, modchan: discord.Channel):
        """
        Set the mods' channel, where all ban logs will print.

        modchan: The mods' channel.
        """
        self.mod_channel = modchan
        await self.bot.send_message(modchan, "Okay {}, I'll send logs in here "
                                             "now.".format(ctx.message.author.mention))

    async def ban_scheduling(self):
        while self == self.bot.get_cog('AdvancedBans'):
            await self.lock.acquire()
            if self.queue.qsize() != 0:
                now = int(time())
                next_tuple = await self.queue.get()
                next_time = next_tuple[0]
                next_case = next_tuple[1]
                diff = next_time - now
                diff = diff if diff >= 0 else 0
                if diff < 5:
                    user = await self.bot.get_user_info(next_case.id)
                    server = self.bot.get_server(next_case.server)
                    log.info("Hop hop hop! Time to unban {}!".format(next_case.name))
                    await self.bot.unban(server, user)
                    del self.bans_data[next_case.server][next_case.id]
                    self.save_bans_data()
                else:
                    log.debug("Will run unban of {} in {}s".format(next_case.name, diff))
                    await self.post_case(next_case, next_time)
            self.lock.release()
            await asyncio.sleep(5)

        while self.queue.qsize() != 0:
            await self.queue.get()


def check_folders():
    if not os.path.exists("data/bans"):
        os.makedirs("data/bans")


def check_files():
    if not os.path.exists(BANS_DATA_FILE):
        dataIO.save_json(BANS_DATA_FILE, {})


def setup(bot):
    check_folders()
    check_files()
    n = AdvancedBans(bot)
    loop = asyncio.get_event_loop()
    loop.create_task(n.ban_scheduling())
    bot.add_cog(n)
