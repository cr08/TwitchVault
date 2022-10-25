# TwitchVault
Simplified tool to automatically archive VODs, clips, highlights, including associated chat logs for specified Twitch channels
***
## Concept
My personal goal has been to find or develop a tool that can not only automate archiving the latest VODs, clips, and highlights from selected Twitch channels, but also archiving the chat logs as they are available for each medium.

So far in my nearly exhaustive search I have been unable to find a tool that can check all the boxes and do so in an automated fashion. Now the plan is to try and develop something to meet these needs.
## WIP/planning stage
Currently I intend to either write the script in a shell/bash script or python depending on complexity and third party tool use.

Following is a working theory of how the script will function:

* Script startup: Read out file containing list of channel ID's
  * Pull list of VODs/highlights for channel `<x>` (optionally add an `--initial` flag to pull a full VOD list or a high limit like 100 videos. Default experience should be looking at the past 24-48h depending on the schedule interval)
    * Iterate through list of VODs, downloading the VOD then the associated chat. Upon confirmed completion of each download step, write VOD ID to a permanent log file. At beginning of this stage, we'll cross-check against said log and ignore any VODs/chats that have already been downloaded.
  * Pull list of available clips for channel `<x>`
    * Iterate through list of VODs, cross-checking permanent log file so that we may ignore clips already downloaded. As new clips and associated chats (if available) are downloaded, write the clip ID to permanent log to confirm completion.
* Rinse and repeat for each channel until the list of channel ID's has been exhausted for this run. Shut down script until the next cycle.