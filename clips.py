# !/usr/bin/env python3

import twitch  # pip install python-twitch-client
import yaml  # pip install PyYAML

import os
import json
import sys
import time
import subprocess
import utils
import datetime
import shutil

# importing static-ffmpeg and pre-downloading
import static_ffmpeg
static_ffmpeg.add_paths()

# authentication information
path_base = os.path.dirname(os.path.abspath(__file__))
config_file = path_base + "/config/config.yaml"
with open(config_file) as f:
    conf = yaml.load(f, Loader=yaml.FullLoader)
client_id = conf["client_id"]
client_secret = conf["client_secret"]

clips_config = path_base + "/config/clips.yaml"
with open(clips_config) as g:
    clips = yaml.load(g, Loader=yaml.FullLoader)
channels = clips["channels"]
min_view_counts = clips["min_view_counts"]
num_days_to_query = clips["num_days_to_query"]

# number of days to try to request
date_start = (datetime.datetime.now()-datetime.timedelta(days=num_days_to_query)).strftime('%Y-%m-%dT%H:%M:%SZ')
date_end = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
print("Start Day: "+date_start)
print("End Day: "+date_end)

# Check for ffmpeg path as installed by static-ffmpeg and the installed version of python/pip
#   A full path is needed for TwitchDownloader

ffmpeg_path = shutil.which('ffmpeg')

# ================================================================
# ================================================================

# paths of the cli and data
tdcli = conf["twitchdownloader"]
path_twitch_cli = path_base + tdcli
path_root = clips["clip_downloads"]
path_temp = clips["clip_temp"]

# ================================================================
# ================================================================

# setup control+c handler
utils.setup_signal_handle()

# convert the usernames to ids (sort so the are in the same order)
client_helix = twitch.TwitchHelix(client_id=client_id, client_secret=client_secret)
client_helix.get_oauth()
users_tmp = client_helix.get_users(login_names=channels)
users = []
for channel in channels:
    for user in users_tmp:
        if user["login"].lower() == channel.lower():
            users.append(user)
            break

# now lets loop through each user and make sure we have downloaded
# their most recent VODs and if we have not, we should download them!
t0 = time.time()
gameid2name = {}
count_total_clips_checked = 0
count_total_clips_downloaded = 0
for idx, user in enumerate(users):

    # check if we should download any more
    if utils.terminated_requested:
        print('terminate requested, not looking at any more users...')
        break

    # check if the directory is created
    path_data = path_root + "/" + user["login"].lower() + "/"
    if not os.path.exists(path_data):
        os.makedirs(path_data)
    if not os.path.exists(path_temp):
        os.makedirs(path_temp)

    # get the videos for this specific user
    try:
        print("getting clips for -> " + user["login"] + " (id " + str(user["id"]) + ")")
        client_helix = twitch.TwitchHelix(client_id=client_id, client_secret=client_secret)
        client_helix.get_oauth()
        vid_iter = client_helix.get_clips(broadcaster_id=user["id"], page_size=100,
                                          started_at=date_start, ended_at=date_end)
        # vid_iter = client_helix.get_clips(broadcaster_id=user["id"], page_size=100)
        # arr_clips = []

        for video in vid_iter[:]:

            # check if we should download any more
            if utils.terminated_requested:
                print('terminate requested, not downloading any more..')
                break
            # time.sleep(random.uniform(0.0, 0.5))
            count_total_clips_checked = count_total_clips_checked + 1

            # don't download any videos below our viewcount threshold
            # NOTE: twitch api seems to return in largest view count to smallest
            # NOTE: thus once we hit our viewcount limit just stop...
            if video['view_count'] < min_view_counts[idx]:
                # print("skipping " + video['url'] + " (only " + str(video['view_count']) + " views)")
                # continue
                break

            # nice debug print
            # arr_clips.append(video)
            print("processing " + video['url'] + " (" + str(video['view_count']) + " views)")

            # INFO: always save to file so our viewcount gets updated!
            # INFO: we only update the viewcount, as when the VOD gets deleted most elements are lost
            file_path_info = path_data + str(video['created_at'].strftime('%Y%m%d T%H%M%SZ')) + " - " +  str(video['id']) + " - " + utils.cleanFilename(str(video['title']))  + "_clip_info.json"
            if not utils.terminated_requested and not os.path.exists(file_path_info):
                print("\t- saving clip info: " + file_path_info)

                # load the game information if we don't have it
                # note sometimes game_id isn't defined (unlisted)
                # in this case just report an empty game
                if video['game_id'] not in gameid2name:
                    game = client_helix.get_games(game_ids=[video['game_id']])
                    if len(game) > 0 and video['game_id'] == game[0]['id']:
                        gameid2name[game[0]['id']] = game[0]['name']
                        game_title = gameid2name[video['game_id']]
                    else:
                        game_title = ""
                else:
                    game_title = gameid2name[video['game_id']]

                # have to call the graphql api to get where the clip is in the VOD
                clip_data = utils.get_clip_data(video['id'])

                # finally write to file
                data = {
                    'id': video['id'],
                    'video_id': video['video_id'],
                    'video_offset': clip_data['offset'],
                    'creator_id': video['creator_id'],
                    'creator_name': video['creator_name'],
                    'title': video['title'],
                    'game_id': video['game_id'],
                    'game': game_title,
                    'url': video['url'],
                    'view_count': video['view_count'],
                    'duration': clip_data['duration'],
                    'created_at': video['created_at'].strftime('%Y-%m-%d %H:%M:%SZ'),
                    'created_at_iso': video['created_at'].strftime('%Y%m%d T%H%M%SZ')
                }
                with open(file_path_info, 'w', encoding="utf-8") as file:
                    json.dump(data, file, indent=4)

            # elif not utils.terminated_requested:
            #     print("\t- updating clip info: " + str(video['view_count']) + " views")
            #     with open(file_path_info) as f:
            #         video_info = json.load(f)
            #     # update view count
            #     video_info["view_count"] = video['view_count']
            #     # update clip location if failed before
            #     if video_info["video_offset"] == -1:
            #         clip_data = utils.get_clip_data(video['id'])
            #         if clip_data['offset'] != -1:
            #             video_info["video_offset"] = clip_data['offset']
            #             video_info["duration"] = clip_data['duration']
            #     # finally write to file
            #     with open(file_path_info, 'w', encoding="utf-8") as file:
            #         json.dump(video_info, file, indent=4)


            # VIDEO: check if the file exists
            file_path = path_data + str(video['created_at'].strftime('%Y%m%d T%H%M%SZ')) + " - " + str(video['id']) + " - " + utils.cleanFilename(str(video['title']))  + "_clip.mp4"
            file_path_tmp = path_temp + str(video['id']) + ".mp4"

            if not utils.terminated_requested and not os.path.exists(file_path):
                print("\t- download clip: " + str(video['id']))
                cmd = path_twitch_cli + ' -m ClipDownload' \
                      + ' --id ' + str(video['id']) + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                      + ' -o ' + file_path_tmp
                      #+ ' --temp-path "' + path_root + '/TEMP/" --quality 1080p60 -o ' + file_path
                # print("\t- CMD: " + str(cmd))
                # subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
                subprocess.Popen(cmd, shell=True).wait()
                shutil.move(file_path_tmp, file_path) 
                count_total_clips_downloaded = count_total_clips_downloaded + 1

            # CHAT: check if the file exists
            file_path_chat = path_data + str(video['created_at'].strftime('%Y%m%d T%H%M%SZ')) + " - " + str(video['id']) + " - " + utils.cleanFilename(str(video['title']))  + "_clip_chat.json"
            file_bad = file_path_chat + ".BAD"
            file_path_chat_tmp = path_temp + str(video['id']) + "_chat.json"
            if os.path.exists(file_bad) or os.path.exists(file_path_chat):
                print("\t- chat file exists - Skipping Chat download")
            else:
                if not utils.terminated_requested:
                    print("\t- download chat: " + str(video['id']) + "_chat.json")
                    cmd = path_twitch_cli + ' -m ChatDownload' \
                          + ' --id ' + str(video['id']) + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                          + ' --embed-emotes' + ' -o ' + file_path_chat_tmp
                    # print("\t- CMD: " + str(cmd))

                    # Attempt to download chat log. If it does not exist, TDCLI will produce a non-zero exit code. We create a placeholder file with a .BAD extension to bypass future file checks
                    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    proc.wait()
                    if proc.returncode != 0:
                        print("\t- ERR: Clip has no chat. Either nothing was said or the source VOD is no longer available. Inserting placeholder.")               
                        with open(file_bad, 'w') as fp:
                            fp.write("No chat log for this clip. Either nothing was said or the source VOD is no longer available.")
                    else:
                        print("\t- GOOD: File moved")
                        shutil.move(file_path_chat_tmp, file_path_chat)
                else:
                    print("\t - chat download SKIPPED")

        # # loop through each and download
        # for video in arr_clips:
        #
        #     # check if we should download any more
        #     if terminated_requested:
        #         print('terminate requested, not rendering any more..')
        #         break
        #
        #     # RENDER: check if the file exists
        #     file_path_chat = path_data + str(video['id']) + "_chat.json"
        #     file_path_render = path_data + str(video['id']) + "_chat.mp4"
        #     print("\t- rendering: " + file_path_render)
        #     if os.path.exists(file_path_chat) and not os.path.exists(file_path_render):
        #         cmd = path_twitch_cli + ' -m ChatRender' \
        #               + ' -i ' + file_path_chat + ' --ffmpeg-path "' + path_twitch_ffmpeg + '"' \
        #               + ' -h 1080 -w 320 --framerate 60 --font-size 13' \
        #               + ' -o ' + file_path_render
        #         subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL).wait()

    except Exception as main_e:
        print(main_e)

t1 = time.time()
print("number of checked clips: " + str(count_total_clips_checked))
print("number of downloaded clips: " + str(count_total_clips_downloaded))
print("total execution time: " + str(t1 - t0))
