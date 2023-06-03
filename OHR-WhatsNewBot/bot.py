import discord
from discord.ext import commands
import os
import json
import urllib.request
import textwrap
import re


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

def compare_release_notes(old_notes, new_notes):
    '''
    Takes old_notes (previous release's whatsnew.txt) and the new_notes (nightly whatsnew.txt).
    Returns a list of lines displaying only whats new in the nightly release.
    '''
    # Read the contents of the old release notes
    with open(old_notes, 'r') as old_file:
        old_lines = [line.strip() for line in old_file.readlines() if line.strip()]

    # Read the contents of the new release notes
    with open(new_notes, 'r') as new_file:
        new_lines = [line.strip() for line in new_file.readlines() if line.strip()]

    retval = ""

    # Define common date formats to match
    date_formats = [
        r"%B %d %Y",           # January 3 2016
        r"%B %d, %Y",          # January 3, 2016
        r"%b %d %Y",           # Jan 3 2016
        r"%b %d, %Y",          # Jan 3, 2016
        r"%B %dst %Y",         # January 3rd 2016
        r"%B %dnd %Y",         # January 23rd 2016
        r"%B %drd %Y",         # January 3rd 2016
        r"%B %dth %Y",         # January 3rd 2016
    ]

    # Define a pattern to match common date formats
    date_pattern = r"\b(\w+ \d{1,2}(?:st|nd|rd|th)?,? \d{4})\b"

    i = 0 # For counting how many times we've seen a date.
    for line in new_lines:  
        edit_line = line
        if "***" in edit_line: # Add some extra formatting for new sections (which start with ***)
            edit_line = "\n\n"+edit_line

        match = re.search(date_pattern, edit_line)
        if match != None:
            if i == 0 :
                retval = retval + edit_line.replace(match.group(0),"") + "\n"
                i = i + 1 # We allow the first date in the file to show up (as it is the new update)
            if i > 0:
                # We don't allow any more dates. Second time we see a date it means we're in the previous update.
                return retval
        
        if edit_line not in old_lines:
            # Compare the old release with the new release. If it's new, add it.
            # We use edit_line to ensure the new formatted lines end up in the update.
            retval = retval + edit_line + "\n"       
    
    return retval


def save_from_url(url, file_path):
    ''' 
    Takes a url (preferably a whatsnew.txt) and file_path (where to save it).
    '''
    try:
        urllib.request.urlretrieve(url, file_path)
        print(f"File downloaded successfully and saved as {file_path}")
    except Exception as e:
        print(f"Error occurred while downloading the file: {str(e)}")



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
    old_release_notes_file = 'release.txt'
    new_release_notes_file = 'nightly.txt'
    save_from_url(RELEASE_WHATSNEW_URL,old_release_notes_file)
    save_from_url(NIGHTLY_WHATSNEW_URL,new_release_notes_file)

    # Call the compare_release_notes function
    output_message = compare_release_notes(old_release_notes_file, new_release_notes_file)
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
