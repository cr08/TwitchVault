# TwitchVault
Simplified tool to automatically archive VODs, clips, highlights, including associated chat logs for specified Twitch channels
***
## Concept
My personal goal has been to find or develop a tool that can not only automate archiving the latest VODs, clips, and highlights from selected Twitch channels, but also archiving the chat logs as they are available for each medium.

## Install Guide
0) Ensure __Python 3.6__ minimum is installed.
1) Clone this repository:
    * `git clone https://github.com/cr08/twitch_vod_creator`
2) Install main python depencies:
    * `python3 -m pip install --user -r requirements.txt`
3) Download and place [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader/releases) for your platform into __/thirdparty__
    * Latest release recommended, minimum __1.50.6__ required as it fixes a chat download issue
    * Ensure TwitchDownloaderCLI is set as executable. This may be necessary on \*nix platforms
        * `chmod +x thirdparty/TwitchDownloaderCLI`
4) Copy and fill out all __config/\*.yaml.example__ files as necessary.
    * An application needs to be registered with Twitch from the [Twitch Dev console](https://dev.twitch.tv/) - client ID and secret need to be entered into __config/config.yaml__
5) Run scripts as desired:
    * `python3 videos.py`
    * `python3 clips.py`
6) __Optional__ - Linux targets: Add scripts to crontab using __docs/crontab_script_launcher.sh__
    * `sudo crontab -e`
    * ```
      */25 * * * * /path/to/repo/docs/crontab_script_launcher.sh videos.py
      * */12 * * * /path/to/repo/docs/crontab_script_launcher.sh clips.py
      ```

### Known Issues
* VTT render produces files with a single word displayed at a time (at least as played via VLC). This needs to be fixed. I may just switch this to SRT as Vosk can natively output this and hopefully it outputs correctly. More testing needed here...

## Credit & Attribution

This repo has been heavily modified from [goldbattle's](https://github.com/goldbattle) [Twitch VOD Creator](https://github.com/goldbattle/twitch_vod_creator) - All credit and attribution as well as a huge amount of thanks goes out to them for creating the core functionality of automatically retrieving the requisite content from Twitch.