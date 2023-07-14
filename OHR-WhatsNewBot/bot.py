import os
import posixpath
import time
import json
import traceback
import ohrlogs
import github
import discord
from discord.ext import commands, tasks

# Enable verbose logging to console
verbose = False

github.verbose = verbose

# Globals are loaded from config.
with open("config.json", 'r') as fi:
    CONFIG = json.load(fi)
APP_TOKEN = CONFIG["APP_TOKEN"]
RELEASE_WHATSNEW_URL = CONFIG["RELEASE_WHATSNEW_URL"]
NIGHTLY_CHECK_URL = CONFIG["NIGHTLY_CHECK_URL"]
GITHUB_REPO = CONFIG["GITHUB_REPO"]
GITHUB_BRANCH = CONFIG["GITHUB_BRANCH"]
UPDATES_CHANNEL = CONFIG["UPDATES_CHANNEL"]
# How frequently we check for new nightlies. New nightlies triggers a check for git commits and log changes
MINUTES_PER_CHECK = CONFIG["MINUTES_PER_CHECK"]
# If it's been this long without new nightlies then force a check for git commits and log changes
MAX_CHECK_DELAY_HOURS = CONFIG["MAX_CHECK_DELAY_HOURS"]
COOLDOWN_TIME = CONFIG["COOLDOWN_TIME"]
WHATSNEW_COOLDOWN_TIME = CONFIG["WHATSNEW_COOLDOWN_TIME"]
MSG_SIZE = CONFIG["MSG_SIZE"]
EMBED_SIZE = CONFIG["EMBED_SIZE"]  # Max size of an embed description. Documented as 4096, API error says 6000
CHUNKS_LIMIT = CONFIG["CHUNKS_LIMIT"]  # Max number of whatsnew.txt chunks
STATE_DIR = CONFIG["STATE_DIR"]

if not os.path.isdir(STATE_DIR):
    os.mkdir(STATE_DIR)
os.chdir(STATE_DIR)

class UpdateChecker:
    """Checks for and reports new commits (not finished) or changes to watched_logs in GITHUB_REPO.
    Call check.start() to start periodic checks."""

    watched_logs = ['whatsnew.txt', 'IMPORTANT-nightly.txt']

    def __init__(self, bot):
        self.channel = bot.get_channel(UPDATES_CHANNEL)
        self.repo = github.GitHubRepo(GITHUB_REPO)
        self.branch = GITHUB_BRANCH

        # Attempt to restore saved state
        state = None
        if os.path.isfile('state.json'):
            with open('state.json', 'r') as fi:
                state = json.load(fi)
        if state and state['repo'] == self.repo.user_repo and state['branch'] == self.branch:
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

    def print_state(self):
        "Log internal state, for debugging."
        print("State:")
        print(" last_commit:", self.last_commit.sha)
        print(" ", self.last_commit)
        for logname in self.watched_logs:
            print(f" {logname} commit:", self.log_shas[logname])
        timeout = (self.last_full_check + MAX_CHECK_DELAY_HOURS * 3600 - time.time()) / 3600
        print(" last_full_check:", time.ctime(self.last_full_check), " Builds time out in %.1f hours" % timeout)

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
    async def check(self, ctx = None, force = False):
        """If there have been new builds, or it's been MAX_CHECK_DELAY_HOURS, or force == True,
        then check for and report new commits and changes to IMPORTANT-nightly.txt & whatsnew.txt.
        Returns True if any message was sent.
        ctx:  channel or (command) Context to send to"""
        if verbose:
            print(f"** UpdateChecker.check(force={force}) ", time.asctime())

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



# Discord setup:
intents = discord.Intents.all()
intents.typing = False  # Disable typing events to reduce unnecessary event handling
allowed_channels = list(CONFIG["ALLOWED_CHANNELS"])  # Replace with the desired channel IDs
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
        update_checker.check.start()
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

@bot.command()
async def help(ctx):
    await ctx.send(f"""Available bot commands:
```
  !check                {check.help}
  !nightlies / !builds  {nightlies.help}
  !whatsnew             {whatsnew.help}
  !commit               {commit.help}
```""")

@bot.command()
@commands.max_concurrency(1)
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.guild)
async def check(ctx, force: bool = True):
    "Check for new git/svn commits and changes to whatsnew.txt & IMPORTANT-nightly.txt"
    print("!check", force)
    if ctx.channel.id not in allowed_channels:
        await ctx.send("This command is not allowed in this channel.")
        return
    if not await update_checker.check(ctx, force):
        await ctx.send("No changes.")


@bot.command(aliases = ['nightly', 'builds'])
@commands.max_concurrency(1)
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.guild)
async def nightlies(ctx, minimal: bool = False):
    "Display status of and links to nightly builds."
    print("!nightlies")
    await update_checker.show_nightlies(ctx, minimal = minimal)

@bot.command(hidden = True)
async def rewind_commits(ctx, num: int):
    "(For testing.) Set the bot state to n commits before HEAD."
    print("!rewind_commits", num)
    update_checker.rewind_commits(num)
    await ctx.send("Rewound.")

@bot.command()
@commands.cooldown(1, WHATSNEW_COOLDOWN_TIME, commands.BucketType.guild)
async def whatsnew(ctx):
    "Display whatsnew.txt for current nightlies. Might be pretty long!"
    if ctx.channel.id not in allowed_channels:
        await ctx.send("This command is not allowed in this channel.")
        return
    print("!whatsnew")

    # Don't cache stable whatsnew.txt but just use the most recently downloaded whatsnew.txt
    ohrlogs.save_from_url(RELEASE_WHATSNEW_URL, 'release_whatsnew.txt')
    output_message = ohrlogs.compare_release_notes('release_whatsnew.txt', 'whatsnew.txt', newest_only = True, diff = False)

    # If the output is long split into multiple messages. Format each chunk as a code block
    chunks = list(chunk_message(output_message, formatting = "```{}```"))
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
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(str(error))
        return
    if isinstance(error, commands.errors.CommandNotFound):
        await ctx.send("No such command.")
        return

    print(" --")
    traceback.print_exception(type(error), error, error.__traceback__)
    print("----")

bot.run(APP_TOKEN)
