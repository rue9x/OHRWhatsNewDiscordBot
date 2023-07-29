from datetime import datetime, timezone
import json
import os
import posixpath
import re
import shutil
import sys
import time
import traceback

import discord
from discord.ext import commands, tasks

import ohrlogs
import github
from github import trim_str

sys.path.append(os.path.join(os.getcwd(), "ohark"))

import ohrk.pull_slimesalad as slimesalad
import ohrk.util
import ohrk.gamedb as gamedb


# Enable verbose logging to console
verbose = False

github.verbose = verbose
slimesalad.verbose = verbose

auto_ss_embeds_enabled = True  # Post embed when an SS game is linked to

# Globals are loaded from config.
with open("config.json", 'r') as fi:
    CONFIG = json.load(fi)
APP_TOKEN = CONFIG["APP_TOKEN"]
BOT_INFO = CONFIG["BOT_INFO"]
RELEASE_WHATSNEW_URL = CONFIG["RELEASE_WHATSNEW_URL"]
NIGHTLY_CHECK_URL = CONFIG["NIGHTLY_CHECK_URL"]
GITHUB_REPO = CONFIG["GITHUB_REPO"]
GITHUB_BRANCH = CONFIG["GITHUB_BRANCH"]
ALLOWED_CHANNELS = CONFIG["ALLOWED_CHANNELS"]  # Channel IDs where commands can be used
UPDATES_CHANNEL = CONFIG["UPDATES_CHANNEL"]
# How frequently we check for new nightlies. New nightlies triggers a check for git commits and log changes
MINUTES_PER_CHECK = CONFIG["MINUTES_PER_CHECK"]
# If it's been this long without new nightlies then force a check for git commits and log changes
MAX_CHECK_DELAY_HOURS = CONFIG["MAX_CHECK_DELAY_HOURS"]
SS_CHECK_HOURS = CONFIG["SS_CHECK_HOURS"]
SS_CACHE_SEC = CONFIG["SS_CACHE_SEC"]
COOLDOWN_TIME = CONFIG["COOLDOWN_TIME"]
WHATSNEW_COOLDOWN_TIME = CONFIG["WHATSNEW_COOLDOWN_TIME"]
MSG_SIZE = CONFIG["MSG_SIZE"]
EMBED_SIZE = CONFIG["EMBED_SIZE"]  # Max size of an embed description. Documented as 4096, API error says 6000
GAME_DESCR_EMBED_SIZE = CONFIG["GAME_DESCR_EMBED_SIZE"]  # What to trim game descriptions down to in embeds
CHUNKS_LIMIT = CONFIG["CHUNKS_LIMIT"]  # Max number of whatsnew.txt chunks
STATE_DIR = CONFIG["STATE_DIR"]

if not os.path.isdir(STATE_DIR):
    os.mkdir(STATE_DIR)
os.chdir(STATE_DIR)


def plural(n_or_iterable, suffix = "s"):
    if hasattr(n_or_iterable, '__len__'):
        n = len(n_or_iterable)
    else:
        n = n_or_iterable
    return "" if n == 1 else suffix


class UpdateChecker:
    """Checks for and reports new commits (not finished) or changes to watched_logs in GITHUB_REPO.
    Call check.start() to start periodic checks."""

    watched_logs = ['whatsnew.txt', 'IMPORTANT-nightly.txt']

    def __init__(self, bot):
        self.channel = bot.get_channel(UPDATES_CHANNEL)
        self.repo = github.GitHubRepo(GITHUB_REPO)
        self.branch = GITHUB_BRANCH

        # Attempt to restore saved state
        state = {}
        if os.path.isfile('state.json'):
            with open('state.json', 'r') as fi:
                state = json.load(fi)
        if 'repo' in state and state['repo'] == self.repo.user_repo and state['branch'] == self.branch:
            print("Loading state.json")
            self.last_full_check = state['last_full_check']
            self.last_commit = github.GitCommit(None, _load_from_dict = state['last_commit'])
            self.log_shas = state['log_shas']
            # The log files will already be downloaded
        else:
            print("No/invalid state.json, initialising state")
            self.last_full_check = time.time()
            self.last_commit = self.repo.last_commits(self.branch, 1)[0]
            self.log_shas = {}
            for logname in self.watched_logs:
                self.log_shas[logname] = self.repo.last_sha_touching(self.branch, logname)
                self.download_revision(self.log_shas[logname], logname)
            # Don't need to download gamedump.php, self.check_ss_gamelist() will.
            self.save_state()

        if verbose:
            self.print_state()

    def save_state(self):
        with open('state.json', 'w') as fo:
            fo.write(json.dumps({
                'repo': self.repo.user_repo,
                'branch': self.branch,
                'last_commit': vars(self.last_commit),
                'log_shas': self.log_shas,
                'last_full_check': self.last_full_check,
            }, indent = '\t'))

    def state_info(self):
        ret =  " last_commit: " + self.last_commit.sha + "\n"
        ret += "  " + str(self.last_commit) + "\n"
        for logname in self.watched_logs:
            ret += f" {logname} commit: " + self.log_shas[logname][:8] + "\n"
        timeout = (self.last_full_check + MAX_CHECK_DELAY_HOURS * 3600 - time.time()) / 3600
        ret += " last_full_check: " + time.ctime(self.last_full_check) + "  Builds time out in %.1f hours\n" % timeout
        return ret

    def print_state(self):
        "Log internal state, for debugging."
        print("State:")
        print(self.state_info())

    def file_url(self, repo_path):
        return self.repo.blob_url(self.branch, repo_path)

    def download_revision(self, ref, repo_path, dest_path = None):
        "Download a file from git at a certain ref (a sha, branch or tag)"
        if not dest_path:
            dest_path = repo_path
        url = self.repo.blob_url(ref, repo_path)
        ohrlogs.save_from_url(url, dest_path)

    async def message(self, msg, ctx = None, **kwargs):
        print("message:", msg)
        if ctx:
            channel = ctx
        else:
            channel = self.channel
        await channel.send(msg, silent = True, **kwargs)

    async def report_commits(self, commits, ctx = None):
        "Send a message listing 'commits' (as an embed)"
        msg = '\n'.join(cmt.short_format(hyperlink = True) for cmt in commits)
        first = True
        print(msg)
        for chunk in chunk_message(msg, EMBED_SIZE):
            embed = discord.Embed()
            if first:
                embed.title = "New commits to " + GITHUB_REPO + " " + self.branch
                embed.url = f'https://github.com/{GITHUB_REPO}/commits/'
                first = False
            embed.description = chunk
            await self.message("", ctx, embed = embed)

    def rewind_commits(self, n):
        "Rewind the state to n commits before HEAD. For debugging."
        self.last_commit = self.repo.last_commits(self.branch, n + 1)[-1]
        # Although this commit didn't necessarily touch the log files, this
        # has the effect of replaying any changes to them since.
        for logname in self.watched_logs:
            self.log_shas[logname] = self.last_commit.sha
            self.download_revision(self.last_commit.sha, logname)
        self.save_state()

    @tasks.loop(minutes = MINUTES_PER_CHECK)
    async def check_ohrdev(self, ctx = None, force = False):
        """If there have been new builds, or it's been MAX_CHECK_DELAY_HOURS, or force == True,
        then check for and report new commits and changes to IMPORTANT-nightly.txt & whatsnew.txt.
        Returns True if any message was sent.
        ctx:  channel or (command) Context to send to"""
        if verbose:
            print(f"** UpdateChecker.check_ohrdev(force={force}) ", time.asctime())

        proceed = False
        if force:
            proceed = True
        elif time.time() > self.last_full_check + MAX_CHECK_DELAY_HOURS * 3600:
            if verbose:
                print("MAX_CHECK_DELAY_HOURS exceeded")
            proceed = True

        nightlies_changed = ohrlogs.url_changed(NIGHTLY_CHECK_URL, 'nightly-check.ini')
        if nightlies_changed:
            proceed = True
        if verbose:
            print("nightlies_changed =", nightlies_changed)

        if proceed == False:
            return False

        self.last_full_check = time.time()

        logs_changed = False
        if await self.check_git(ctx):
            logs_changed = await self.check_logs(ctx)  # Also shows_nightlies if true
        if verbose:
            print("logs_changed =", logs_changed)

        if verbose:
            self.print_state()

        return logs_changed

    async def check_git(self, ctx = None):
        """Check for new commits. Returns True if any message was sent.
        ctx:  channel or (command) Context to send to"""

        new_repo_sha = self.repo.current_sha(self.branch)
        if new_repo_sha == self.last_commit.sha:
            if verbose:
                print(" No new commits")
            return False
        if verbose:
            print(" New HEAD", new_repo_sha)

        # Limited to at most 100 new commits at a time.
        new_commits = self.repo.last_commits(self.branch, 100, since = self.last_commit)
        await self.report_commits(new_commits, ctx)
        # Update .last_commit once report_commits succeeds. If log file messages fail to send
        # we'll pick them up the next time there's a commit, although not on the next check().
        self.last_commit = new_commits[0]
        self.save_state()
        return True

    async def check_logs(self, ctx = None):
        """Check for changes to logs. Returns True if any message was sent.
        Also, will show_nightlies if there are any log changes.
        ctx:  channel or (command) Context to send to"""
        ret = False

        for logname in self.watched_logs:
            # (Optional) Check whether the file actually changed before downloading it
            new_sha = self.repo.last_sha_touching(self.branch, logname)
            if new_sha == self.log_shas[logname]:
                continue

            # Download specifying the exact sha to download rather than just the branch, as otherwise
            # github seems to cache it rather than providing actual latest.
            self.download_revision(new_sha, logname, logname + '.new')

            changes = ohrlogs.compare_release_notes(logname, logname + '.new')
            if changes:
                msg = f"{logname} changes (as of {self.last_commit.rev()}):\n```{changes}```"
                if ret:  # Already showed nightlies
                    await self.message(msg, ctx)
                else:
                    await self.show_nightlies(ctx, msg, minimal = True)
                ret = True
            else:
                if verbose:
                    print(" No text changes to", logname)

            # Update state once the update is posted successfully
            self.log_shas[logname] = new_sha
            os.rename(logname + '.new', logname)
            self.save_state()

        return ret

    async def show_nightlies(self, ctx = None, msg_prefix = "", minimal = False):
        "Send a message with links to nightlies. Doesn't change state"

        builds = ohrlogs.get_builds(NIGHTLY_CHECK_URL)
        nightly_dir = posixpath.split(NIGHTLY_CHECK_URL)[0]
        max_rev = max(build.svn_rev for build in builds)
        # Also warn if out of date with the last commit (or whatsnew.txt update) we showed
        max_rev = max(max_rev, self.last_commit.svn_rev)
        min_rev = min(build.svn_rev for build in builds)
        max_date = max(build.build_date for build in builds)

        view = discord.ui.View()
        for build in builds:
            if minimal and not build.important:
                continue
            if build.svn_rev < max_rev:
                emoji = "💤"  # Indicate it's out of date
            else:
                emoji = None
            but = discord.ui.Button(label = build.label(), url = build.url, emoji = emoji)
            view.add_item(but)

        but = discord.ui.Button(label = "See all", url = nightly_dir, emoji = "📁")
        view.add_item(but)

        msg = msg_prefix + "\nNightly build downloads"
        if not minimal:
            msg += " and commit built, latest built " + str(max_date)
        if max_rev > min_rev:
            msg += " (some are behind)"
        if minimal:
            msg += "; `!nightlies` shows more"
        await self.message(msg, ctx, view = view)

    @tasks.loop(hours = SS_CHECK_HOURS)
    async def check_ss_gamelist(self):
        "Fetch SS gamedump and announce new & changed games"
        if verbose:
            print(f"** UpdateChecker.check_ss_gamelist() ", time.asctime())

        new_path = ohrk.scrape.download_url(slimesalad.GAMEDUMP_URL, cache = False)
        old_path = 'gamedump.php'  # In state/

        if not os.path.isfile(old_path):
            # First run
            shutil.copyfile(new_path, old_path)
            return

        added, removed, changed = slimesalad.compare_gamedumps(old_path, new_path)

        if verbose and added:
            print("New SS games:")
        for gameinfo in added:
            if verbose:
                print(gameinfo.serialize())
            # Cache for a few seconds to avoid redownloading gamedump.php
            embed = ss_game_embed(gameinfo.url, cache = 10)
            #print(f"New release on Slime Salad: {gameinfo.name} by {gameinfo.author}")
            await self.message(f"[Slime Salad] New release: **{gameinfo.name}** by {gameinfo.author}", embed = embed)

        # We don't post updates about removed games.
        if verbose and removed:
            print("Removed SS games:")
            for gameinfo in removed:
                print(gameinfo.serialize())

        if verbose and changed:
            print("Changed SS games:")
        for old, new in changed:
            if verbose:
                print(old.serialize())
                print(' -> ')
                print(new.serialize())

            desc = ""
            if old.name != new.name:
                desc += "\n(Renamed from **" + old.name + "**)"
            # Just the downloads, not the .pics
            new_files = dict((f.serialize(), f) for f in new.files)
            old_files = dict((f.serialize(), f) for f in old.files)

            added_files = []
            for ser, gamefile in new_files.items():
                if ser not in old_files:
                    added_files.append(gamefile.name)
            if len(added_files):
                desc += f"\nNew download{plural(added_files)} " + ", ".join(added_files) + "\n"

            # for ser, gamefile in old_files.items():
            #     if ser not in new_files:
            #         desc += "\nRemoved download " + gamefile.name
            # We don't mention change in author name, removed downloads
            # (they're usually replaced), new screenshots, or description
            # (would have to scrape the page for that).

            if desc == "":
                # No changes significant enough to post an update.
                continue

            # Don't cache when known to have changed
            embed = ss_game_embed(new.url, cache = 10, show_dl_dates = True)
            #print(f"Update to {new.name} by {new.author} on Slime Salad{desc}")
            await self.message(f"[Slime Salad] Update to **{new.name}** by {new.author}{desc}", embed = embed)

        # Update state once the update is posted successfully
        shutil.copyfile(new_path, old_path)  # Leave copy in the cache


def ss_game_embed(url, cache = SS_CACHE_SEC, show_update_date = False, show_dl_dates = False):
    """Create an Embed for a Slime Salad game page
    show_update_date: show when the game description or downloads were last updated.
    show_dl_dates: show mtimes for each download."""

    try:
        game = slimesalad.process_game_page(url, download_screens = False, cache = cache)
    except Exception as err:
        print(f"slimesalad.process_game_page({url}) failed:", err)
        return None

    desc = trim_str(ohrk.util.strip_html(game.description), GAME_DESCR_EMBED_SIZE)

    # Call these after process_game_page, because we can only convert ?p=... links to ?t=...
    # links (necessary for finding the game in gamedump.php) after processing the
    # page (which updates slimesalad.link_db), unless we preprocess them all and save the db.
    url = slimesalad.normalise_game_url(url)
    gameinfo = slimesalad.get_gameinfo(url, cache = cache)

    embed = discord.Embed()
    embed.provider.name = "Slime Salad"
    embed.title = game.name
    embed.set_author(name = game.author)
    embed.description = desc
    embed.url = url

    if game.screenshots:
        # SS used to show the last screenshot as the thumbnail for the game
        embed.set_image(url = game.screenshots[-1].url)

    def epoch_date_str(t):
        "Format Unix timestamp as a date"
        return time.strftime("%Y/%m/%d", time.gmtime(t))

    downloads_by_date = []
    for download in game.downloads:
        description = download.description
        if description is None:
            description = ""
        mtime = 0
        if gameinfo:
            gamefile = gameinfo.file_by_url(download.external)
            if gamefile:
                # gamefile.date is a datetime
                mtime = gamefile.date.timestamp()
                if show_dl_dates:
                    description = epoch_date_str(mtime) + " " + description
                elif description == "":
                    description = download.sizestr
        downloads_by_date.append( (mtime, download.name(), description) )
    # Show only latest downloads
    downloads_by_date.sort(reverse = True)

    max_downloads = 4

    # Game last modified, also tell last download mtime if it differs
    if show_update_date:
        # game.mtime (which can be None) for many games is just when it was originally posted
        mtime = game.mtime or 0
        if downloads_by_date:
            mtime = max(mtime, downloads_by_date[0][0])  # latest download mtime
        if mtime:
            embed.add_field(name = "Last update", value = epoch_date_str(mtime))
            max_downloads -= 1

    # Downloads
    for _, name, description in downloads_by_date[:max_downloads]:
        embed.add_field(name = name, value = trim_str(description, 65))
    if len(downloads_by_date) > max_downloads:
        more_downloads = ", ".join(name for _,name,_ in downloads_by_date[max_downloads:])
        embed.add_field(name = "More downloads", value = trim_str(more_downloads, 100))

    if game.reviews:
        review_authors = [review.author for review in game.reviews]
        embed.add_field(name = f"{len(game.reviews)} review" + plural(game.reviews),
                        value = trim_str("by " + ", ".join(review_authors), 100))

    return embed


# Discord setup:
intents = discord.Intents.all()
intents.typing = False  # Disable typing events to reduce unnecessary event handling
bot = commands.Bot(command_prefix = "!", intents = intents, help_command = None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    print ("Started OHR WhatsNew Bot")
    print("------")
    if not bot.get_channel(UPDATES_CHANNEL):
        print("ERROR: invalid UPDATES_CHANNEL")
    else:
        global update_checker
        update_checker = UpdateChecker(bot)
        update_checker.check_ohrdev.start()
        update_checker.check_ss_gamelist.start()
    # Be cute
    await bot.change_presence(activity = discord.Activity(type = discord.ActivityType.watching, name = "OHRRPGCE changes"))

def chunk_message(message, chunk_size = MSG_SIZE, formatting = "{}"):
    "Split a string at line breaks into chunks at most chunk_size in length."
    while len(message):
        # Split off a chunk at the last newline before chunk_size
        if len(message) > chunk_size:
            break_index = message[:chunk_size].rfind('\n')
            if break_index == -1:
                break_index = chunk_size
        else:
            break_index = len(message)
        yield formatting.format(message[:break_index])
        message = message[break_index:]

async def allowed_channel(ctx):
    if ctx.channel.id not in ALLOWED_CHANNELS:
        #await ctx.send("This command is not allowed in this channel.")
        return False
    return True

@bot.listen('on_message')
#@commands.cooldown(1, 10, commands.BucketType.user)
async def message_listener(message):
    "Called for each message, watches for links to SS games, and posts an embed."
    if message.author == bot.user:
        return
    if auto_ss_embeds_enabled or bot.user.mentioned_in(message):
        if message.embeds:
            return
        match = re.search('(https?://)?www.slimesalad.com/forum/view(topic|game).php\?([pt])=([0-9]+)', message.content)
        if match:
            if verbose:
                print(f"Generating SS embed for message by {message.author} in {message.channel}: {message.content}")
            embed = ss_game_embed(match.group(0), show_update_date = True)
            if embed:
                await message.channel.send("", embed = embed)


@bot.command()
@commands.check(allowed_channel)
async def help(ctx):
    await ctx.send(f"""Available bot commands:
```
  !check                {check.help}
  !commit r####/sha     {commit.help}
  !info                 {info.help}
  !nightlies / !builds  {nightlies.help}
  !whatsnew [release]   {whatsnew.help}
  !disable_embeds       {disable_embeds.help}
  !enable_embeds        {enable_embeds.help}
```""")

@bot.command()
@commands.check(allowed_channel)
@commands.max_concurrency(1)
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.guild)
async def check(ctx, force: bool = True):
    "Check for new git/svn commits and changes to whatsnew.txt & IMPORTANT-nightly.txt."
    print("!check", force)
    if not await update_checker.check_ohrdev(ctx, force):
        await ctx.send("No changes.")

@bot.command()
@commands.check(allowed_channel)
@commands.cooldown(5, COOLDOWN_TIME, commands.BucketType.user)
async def commit(ctx, rev: str):
    "Show a specific commit: an svn revision like 'r12345' or git commit like 'd8cf256'."
    print("!commit " + rev)
    try:
        ref = update_checker.repo.decode_rev(rev)
    except ValueError:
        await ctx.send("Invalid svn revision or git commit SHA, should look like 'r10000' or 'd8cf256'")
        return
    except KeyError:
        await ctx.send(f"Couldn't find {rev}, the bot hasn't seen that commit.")
        return

    try:
        commit = update_checker.repo.last_commits(ref, 1)[0]
    except github.GitHubError as err:
        await ctx.send(str(err))
    else:
        msg = trim_str(commit.format(), MSG_SIZE)
        await ctx.send(msg)

# Allowed in all channels
@bot.command()
async def disable_embeds(ctx):
    "Stop the bot from showing embeds for links to SS games, unless it's mentioned."
    print("!disable_embeds")
    global auto_ss_embeds_enabled
    auto_ss_embeds_enabled = False
    await ctx.send(f"Disabled. Add @{bot.user} to see SS embed")


# Allowed in all channels
@bot.command()
async def enable_embeds(ctx):
    "Automatically show an embed whenever an SS game link is posted."
    print("!disable_embeds")
    global auto_ss_embeds_enabled
    auto_ss_embeds_enabled = True
    await ctx.send("Enabled")

@bot.command()
@commands.check(allowed_channel)
async def info(ctx):
    "Display bot info and status."
    print("!info")
    msg = BOT_INFO + "\n"
    msg += f"Watching https://github.com/{GITHUB_REPO}/commits/{GITHUB_BRANCH}\n"
    msg += "Current status:\n```" + update_checker.state_info() + "```\nUse `!help` for help."
    await ctx.send(msg, suppress_embeds = True)

@bot.command(aliases = ['nightly', 'builds'])
@commands.check(allowed_channel)
@commands.max_concurrency(1)
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.guild)
async def nightlies(ctx, minimal: bool = False):
    "Display status of and links to nightly builds."
    print("!nightlies")
    await update_checker.show_nightlies(ctx, minimal = minimal)

@bot.command(hidden = True)
@commands.check(allowed_channel)
async def rewind_commits(ctx, num: int):
    "(For testing.) Set the bot state to n commits before HEAD."
    print("!rewind_commits", num)
    update_checker.rewind_commits(num)
    await ctx.send("Rewound.")

@bot.command()
@commands.check(allowed_channel)
@commands.cooldown(2, WHATSNEW_COOLDOWN_TIME, commands.BucketType.guild)
async def whatsnew(ctx, release: str = None):
    "Display whatsnew.txt for a specific release, or by default for current nightlies."
    print("!whatsnew")

    # Just use the most recently downloaded whatsnew.txt
    notes, error = ohrlogs.specific_release_notes('whatsnew.txt', release)
    if error:
        await ctx.send(error)
        return

    # If the output is long split into multiple messages. Format each chunk as a code block
    chunks = list(chunk_message(notes, formatting = "```{}```"))
    if len(chunks) > CHUNKS_LIMIT:
        chunks = chunks[:CHUNKS_LIMIT]
        chunks.append("(snip) ...Too much is new! View the whole file here:")

    for chunk in chunks:
        view = None
        if chunk == chunks[-1]:
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label = "Stable whatsnew.txt", url = RELEASE_WHATSNEW_URL))
                view.add_item(discord.ui.Button(label = "Nightly whatsnew.txt", url = update_checker.file_url('whatsnew.txt'), emoji = '🛠️'))
        await ctx.send(chunk, view = view, silent = True)

@bot.event
async def on_command_error(ctx, error):
    print("on_command_error:", error)
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'This command is on cooldown, you can use it in {int(error.retry_after)} seconds.')
        return
    if isinstance(error, commands.errors.MaxConcurrencyReached):
        return  # Ignore
    if isinstance(error, commands.errors.CheckFailure):
        return  # Ignore, already printed a message
    if isinstance(error, (commands.errors.MissingRequiredArgument, commands.errors.BadArgument)):
        await ctx.send(str(error))
        return
    if isinstance(error, commands.errors.CommandNotFound):
        await ctx.send("No such command.")
        return

    print(" --")
    traceback.print_exception(type(error), error, error.__traceback__)
    print("----")

bot.run(APP_TOKEN)
