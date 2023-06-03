# OHRWhatsNewDiscordBot

A Discord bot for displaying whatsnew.txt for the OHRRPGCE

# Installation:

1. Install Python3 (https://www.python.org/downloads/)

2. Install module requirements: pip install -r requirements.txt

3. Make a copy of example_config.json, name it config.json and add your APP_TOKEN and ALLOWED_CHANNELS.

You can get your APP_TOKEN at http://developer.discord.com and the channel IDs can be obtained by
right clicking on a channel on discord and selecting "Copy Channel ID".

# Usage 
1. Launch with: py bot.py -- Success looks like this:

discord.client logging in using static token

discord.gateway Shard ID None has connected to Gateway (Session ID: cdcac418e852ee7fc167f2cb3ab77635).

Logged in as OHR Whats New Bot

Started OHR WhatsNew Bot

2. In one of the discord channels the bot has joined, use !whatsnew.

3. Adjust the COOLDOWN_TIME to change how often a user can use the command. Will require a relaunch.

4. Ctrl+C to kill the bot.

# Known issues

1. (watching) Message truncating is odd.

2. No error control (connection errors, etc)

3. No command to kill bot.
