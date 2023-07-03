import discord
from discord.ext import commands
import os
import json
import ohrwhatsnew

SAVE_FOLDER = ""
SAVE_FOLDER = os.getcwd() + os.sep

# Globals are loaded from config.
with open (os.path.join(SAVE_FOLDER,"config.json"),'r') as fi:
    CONFIG = json.load(fi)
APP_TOKEN = CONFIG["APP_TOKEN"]
NIGHTLY_WHATSNEW_URL = CONFIG["NIGHTLY_WHATSNEW_URL"]
RELEASE_WHATSNEW_URL = CONFIG["RELEASE_WHATSNEW_URL"] 
COOLDOWN_TIME = CONFIG["COOLDOWN_TIME"]
MSG_SIZE = CONFIG["MSG_SIZE"]

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
    print("command_error:", error)
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'This command is on cooldown, you can use it in {round(error.retry_after, 2)} seconds.')

bot.run(APP_TOKEN)
