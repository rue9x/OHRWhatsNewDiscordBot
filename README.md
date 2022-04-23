# OHRWhatsNewDiscordBot
A Discord bot for displaying whatsnew.txt for the OHRRPGCE

Requires:
Python3
Discord.py (pip install discord.py) (yes, literally discord.py, not pip install discord)
urllib (probably included with python3 at this point)
textwrap (probably included with python3 at this point)

Usage: 
1. Open up bot.py in a text editor of your choice.
2. Put your discord bot API token in the APP_TOKEN variable (as a string)
3. Save.
4. Tell your bot where to go using Discords bot control panel.
5. Launch with bot.py

Successful launch will hang and have a message saying: "OHRRPGCE What's New Bot is in # guilds." (where # is the number of channels the bot is in.

Commands:
!whatsnew (nightly or release)

Pulls down the nightly (or release) whatsnew.txt for the MOST RECENT version of the OHR. Nightly is the most recent nightly, obviously. 

!help whatsnew
Displays some really obvious help.

There is currently a 30 second timeout _per server_ for using this command. You can easily write it out, but, you don't really want to go around spamming people with a ton of text, or ddosing the whatsnew.txt. :P


Known issues:
No error handling. If you use !whatsnew with no argument, it'll complain about it in the console, but it doesn't hurt the bot any.
