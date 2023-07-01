import discord
from discord.ext import commands
import os
import json
import textwrap
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

@bot.command()
@commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.user)
async def whatsnew(ctx):
    if ctx.channel.id not in allowed_channels:
        await ctx.send("This command is not allowed in this channel.")
        return

    output_message = ohrwhatsnew.compare_urls(RELEASE_WHATSNEW_URL, NIGHTLY_WHATSNEW_URL)

    # Split the output message into chunks at word boundaries
    wrapped_message = textwrap.wrap(output_message, width=2000, break_long_words=False,replace_whitespace=False)
    
    # Send each chunk as a separate message, formatted in code blocks
    for chunk in wrapped_message:
        # Find the last space character within the 2000-character limit
        last_space_index = chunk[:MSG_SIZE].rfind(' ')
        
        # Truncate the chunk to the last space character, or the 2000-character limit if no space found
        truncated_chunk = chunk[:last_space_index] if last_space_index != -1 else chunk[:MSG_SIZE]
        
        formatted_chunk = f"```{truncated_chunk}```"
        await ctx.send(formatted_chunk)
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f'This command is on cooldown, you can use it in {round(error.retry_after, 2)} seconds.')

bot.run(APP_TOKEN)
