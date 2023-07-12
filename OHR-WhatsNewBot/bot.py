import discord
from discord.ext import commands, tasks
import os
import json
import traceback
import ohrwhatsnew
import github

# Enable verbose logging to console
verbose = False

github.verbose = verbose

SAVE_FOLDER = os.getcwd()

# Globals are loaded from config.
with open (os.path.join(SAVE_FOLDER,"config.json"),'r') as fi:
    CONFIG = json.load(fi)
APP_TOKEN = CONFIG["APP_TOKEN"]
RELEASE_WHATSNEW_URL = CONFIG["RELEASE_WHATSNEW_URL"]
GITHUB_REPO = CONFIG["GITHUB_REPO"]
GITHUB_BRANCH = CONFIG["GITHUB_BRANCH"]
UPDATES_CHANNEL = CONFIG["UPDATES_CHANNEL"]
MINUTES_PER_CHECK = CONFIG["MINUTES_PER_CHECK"]
COOLDOWN_TIME = CONFIG["COOLDOWN_TIME"]
MSG_SIZE = CONFIG["MSG_SIZE"]

def save_path(filename):
    return os.path.join(SAVE_FOLDER, filename)


class UpdateChecker:
    """Checks for and reports new commits (not finished) or changes to whatsnew.txt in GITHUB_REPO.
    Call check.start() to start periodic checks."""

    def __init__(self, bot):
        self.repo = github.GitHubRepo(GITHUB_REPO)
        self.branch = GITHUB_BRANCH
        self.last_commit = self.repo.last_commits(self.branch, 1)[0]
        self.current_shas = {}
        #self.current_shas['REPO'] = self.repo.current_sha(self.branch)
        self.current_shas['whatsnew.txt'] = self.repo.last_sha_touching(self.branch, 'whatsnew.txt')
        self.download_revision(self.current_shas['whatsnew.txt'], "whatsnew.txt")

        if verbose:
            self.print_state()

        self.channel = bot.get_channel(UPDATES_CHANNEL)

    def download_revision(self, ref, repo_path, dest_path = None):
        "Download a file from git at a certain ref (a sha, branch or tag)"
        if not dest_path:
            dest_path = repo_path
        url = self.repo.blob_url(ref, repo_path)
        ohrwhatsnew.save_from_url(url, save_path(dest_path))

    async def message(self, msg, ctx = None, **kwargs):
        print(msg)
        if ctx:
            channel = ctx
        else:
            channel = self.channel
        await channel.send(msg, silent = True, **kwargs)

    async def report_commits(self, commits, ctx = None):
        "Send a message listing 'commits' (as an embed)"
        msg = '\n'.join(cmt.short_format(hyperlink = True) for cmt in commits)
        embed = discord.Embed()
        embed.title = "New commits to " + GITHUB_REPO + " " + self.branch
        embed.url = f'https://github.com/{GITHUB_REPO}/commits/'
        embed.description = msg
        print(msg)
        await self.message(ctx, embed = embed)

    def print_state(self):
        "Log internal state, for debugging."
        print("Status:")
        print(" last_commit:", self.last_commit.sha)
        print(" ", self.last_commit)
        print(" whatsnew commit:", self.current_shas['whatsnew.txt'])

    def rewind_commits(self, n):
        "Rewind the state to n commits before HEAD. For debugging."
        self.last_commit = self.repo.last_commits(self.branch, n + 1)[-1]
        # Although this commit didn't necessarily change whatsnew.txt, it
        # has the effect of replaying any changes to it since.
        self.current_shas['whatsnew.txt'] = self.last_commit.sha
        self.download_revision(self.last_commit.sha, 'whatsnew.txt')

    @tasks.loop(minutes = MINUTES_PER_CHECK)
    async def check(self, ctx = None):
        """Check for new commits and for changes to whatsnew.txt.
        Returns True if any message was sent.
        ctx:  channel or (command) Context to send to"""
        if verbose:
            print("UpdateChecker.check")

        new_repo_sha = self.repo.current_sha(self.branch)
        if new_repo_sha == self.last_commit.sha:
            if verbose:
                print("check: No new commits")
            return False
        if verbose:
            print("new REPO sha", new_repo_sha)
        new_commits = self.repo.last_commits(self.branch, 100, since = self.last_commit)
        await self.report_commits(new_commits, ctx)

        # There's been a new commit, but check whether whatsnew.txt actually changed before downloading it
        new_whatsnew_sha = self.repo.last_sha_touching(self.branch, 'whatsnew.txt')
        if new_whatsnew_sha == self.current_shas['whatsnew.txt']:
            if verbose:
                print("new commit, but didn't touch whatsnew.txt")
            self.last_commit = new_commits[0]
            return True
        if verbose:
            print("new whatsnew.txt sha", new_whatsnew_sha)

        # Download specifying the exact sha to download rather than just the branch, as otherwise
        # github seems to cache it rather than providing actual latest.
        self.download_revision(new_whatsnew_sha, "whatsnew.txt", 'whatsnew.txt.new')

        changes = ohrwhatsnew.compare_release_notes(save_path('whatsnew.txt'), save_path('whatsnew.txt.new'))
        if not changes:  # Odd...
            if verbose:
                print("no text changes to whatsnew.txt")
            return True

        await self.message(f"```{changes}```", ctx)

        # Update state only if all messages were sent successfully
        self.last_commit = new_commits[0]
        self.current_shas['whatsnew.txt'] = new_whatsnew_sha
        os.rename(save_path('whatsnew.txt.new'), save_path('whatsnew.txt'))
        return True


# Discord setup:
intents = discord.Intents.all()
intents.typing = False  # Disable typing events to reduce unnecessary event handling
allowed_channels = list(CONFIG["ALLOWED_CHANNELS"])  # Replace with the desired channel IDs
bot = commands.Bot(command_prefix="!", intents=intents)


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

def chunk_message(message):
    "Split a string at line breaks into chunks at most MSG_SIZE in length."
    while len(message):
        # Split off a chunk at the last newline before MSG_SIZE
        if len(message) > MSG_SIZE:
            break_index = message[:MSG_SIZE].rfind('\n')
            if break_index == -1:
                break_index = MSG_SIZE
        else:
            break_index = len(message)
        yield message[:break_index]
        message = message[break_index:]

@bot.command()
async def check(ctx):
    print("!check")
    if ctx.channel.id not in allowed_channels:
        await ctx.send("This command is not allowed in this channel.")
        return
    ret = await update_checker.check(ctx)
    if not ret:
        await ctx.send("No changes.", silent = True)

@bot.command()
async def rewind_commits(ctx, n: int):
    "For testing."
    print("!rewind_commits", n)
    update_checker.rewind_commits(n)
    await ctx.send("Rewound.", silent = True)
    if verbose:
        update_checker.print_state()

@bot.command()
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.user)
async def whatsnew(ctx):
    if ctx.channel.id not in allowed_channels:
        await ctx.send("This command is not allowed in this channel.")
        return

    output_message = ohrwhatsnew.compare_urls(RELEASE_WHATSNEW_URL, NIGHTLY_WHATSNEW_URL)

    # If the output is long split into multiple messages
    for chunk in chunk_message(output_message):
        # Formatted in code blocks
        formatted_chunk = f"```{chunk}```"
        await ctx.send(formatted_chunk)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'This command is on cooldown, you can use it in {int(error.retry_after)} seconds.')

    print("----\n on_command_error:")
    traceback.print_exception(type(error), error, error.__traceback__)
    print("----")

bot.run(APP_TOKEN)
