# OHRWhatsNewDiscordBot

A Discord bot that watches for and reports new git commits, changelog updates (whatsnew.txt and IMPORTANT-nightly.txt) and nightly builds for the OHRRPGCE.

# Installation:

1. Install Python3 (https://www.python.org/downloads/)

2. Install module requirements: pip install -r requirements.txt

3. Make a copy of example_config.json, name it config.json and add your APP_TOKEN, UPDATES_CHANNEL and ALLOWED_CHANNELS (where ! commands can be used).

You can get your APP_TOKEN at http://developer.discord.com and the channel IDs can be obtained by
right clicking on a channel on discord and selecting "Copy Channel ID".

# Usage 
1. Launch with: python3 bot.py -- Success looks like this:

```
discord.client logging in using static token
discord.gateway Shard ID None has connected to Gateway (Session ID: cdcac418e852ee7fc167f2cb3ab77635).
Logged in as OHR Whats New Bot
Started OHR WhatsNew Bot
------
No/invalid state.json, initialising state
```

The bot will then immediately perform its first check.

2. In any of the allowed channels, users can use `!help`, `!check` and other commands.

3. You can use the `!rewind_commits <n>` followed command followed by `!check` to test the bot.

4. Or just do nothing and the bot will post updates once a day, if there are any. It will take up to MINUTES_PER_CHECK after nightly builds are built before it posts any git commits (and log changes) made that day. If MAX_CHECK_DELAY_HOURS (26) pass without new nightly builds, it'll go ahead and post git commits regardless.

5. Ctrl+C to kill the bot. It'll read `state/state.json` and resume where it left off when restarted, without missing anything.

# Known issues

None.
