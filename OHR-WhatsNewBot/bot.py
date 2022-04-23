'''
OHRRPGCE Whatsnew.txt discord bot
2022 Rue Lazzaro
for the Slime Salad community

'''


import discord
from urllib.request import urlopen
import textwrap
import time
from discord.ext import commands

NIGHTLY_WHATSNEW_URL = "https://raw.githubusercontent.com/ohrrpgce/ohrrpgce/wip/whatsnew.txt"
RELEASE_WHATSNEW_URL = "https://hamsterrepublic.com/ohrrpgce/whatsnew.txt"
APP_TOKEN = "" # Get your own app token. :)
MAX_CONTENT_LENGTH = 2000-6 # -6 to supply block formatting.
MSG_DELAY = 3
client = commands.Bot(command_prefix='!')

def get_whatsnew(url):
    content = urlopen(url).read()
    content = (content.decode('utf-8'))
    content = content.split("*** New Features")
    content = content[0] + content[1] # Should just be the most recent release/WIP release.
    split_string = textwrap.wrap(content, MAX_CONTENT_LENGTH,replace_whitespace=False,break_long_words=False)
    del split_string[-1]
    return split_string


@commands.cooldown(rate=1, per=30, type=commands.BucketType.guild)
@client.command(name='whatsnew',help='Retrieves and displays the most recent nightly/release version of whatsnew.txt from HamsterRepublic.')
async def whatsnew(ctx,release_or_nightly:str):
    if release_or_nightly.lower() == "release":
        url_to_use = RELEASE_WHATSNEW_URL

    if release_or_nightly.lower() == "nightly":
        url_to_use = NIGHTLY_WHATSNEW_URL

    if release_or_nightly.lower() == "release" or release_or_nightly.lower() == "nightly":
    # SENDS BACK A MESSAGE TO THE CHANNEL.
        msg = get_whatsnew(url_to_use)
        await ctx.send(f"{release_or_nightly} Whatsnew: {url_to_use}\n----------")
        for each in msg: 
            await ctx.send("```"+each+"```")
            time.sleep(MSG_DELAY)




@client.event
async def on_ready():
    # CREATES A COUNTER TO KEEP TRACK OF HOW MANY GUILDS / SERVERS THE BOT IS CONNECTED TO.
    guild_count = 0

    # LOOPS THROUGH ALL THE GUILD / SERVERS THAT THE BOT IS ASSOCIATED WITH.
    for guild in client.guilds:
        # PRINT THE SERVER'S ID AND NAME.
        print(f"- {guild.id} (name: {guild.name})")

        # INCREMENTS THE GUILD COUNTER.
        guild_count = guild_count + 1

    # PRINTS HOW MANY GUILDS / SERVERS THE BOT IS IN.
    print("OHRRPGCE What's New Bot is in " + str(guild_count) + " guilds.")

@client.event
async def on_message(message):
    if(message.author == client.user):
        return
    try:
        await client.process_commands(message)
    except:
        if "!whatsnew" in message:
            print ("Supplied !whatsnew without argument.")



# EXECUTES THE BOT WITH THE SPECIFIED TOKEN. TOKEN HAS BEEN REMOVED AND USED JUST AS AN EXAMPLE.
client.run(APP_TOKEN)

