# !/usr/bin/env python3

import twitch  # pip install python-twitch-client
import yaml  # pip install PyYAML
from webvtt import WebVTT, Caption  # pip install webvtt-py
from vosk import Model, KaldiRecognizer, SetLogLevel  # pip install vosk
from discord_webhook import DiscordWebhook # pip install discord-webhook

import os
import json
import subprocess
from datetime import datetime
import utils
import time
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

videos_config = path_base + "/config/videos.yaml"
with open(videos_config) as g:
    videos = yaml.load(g, Loader=yaml.FullLoader)
channels = videos["channels"]
max_videos = videos["max_videos"]
render_chat = videos["render_chat"]
render_webvtt = videos["render_webvtt"]

# Check for ffmpeg path as installed by static-ffmpeg and the installed version of python/pip
#   A full path is needed for TwitchDownloader

ffmpeg_path = shutil.which('ffmpeg')

# ================================================================
# ================================================================

# paths of the cli and data
tdcli = conf["twitchdownloader"]
path_twitch_cli = path_base + tdcli
path_root = videos["video_downloads"]
path_temp = videos["video_temp"]
path_model = path_base + "/thirdparty/vosk-model-small-en-us-0.15/"

# ================================================================
# ================================================================

# setup control+c handler
utils.setup_signal_handle()

users = {}
if len(channels) != len(render_chat) or len(channels) != len(render_webvtt):
    print('number of channels and chat render settings do not match!!')
    print('\tlen(channels) = %d' % len(channels))
    print('\tlen(users) = %d' % len(users))
    print('\tlen(render_chat) = %d' % len(render_chat))
    print('\tlen(render_webvtt) = %d' % len(render_webvtt))
    exit(-1)

# convert the usernames to ids (sort so the are in the same order)
client_helix = twitch.TwitchHelix(client_id=client_id, client_secret=client_secret)
client_helix.get_oauth()
users_tmp = client_helix.get_users(login_names=channels)
users = []
render_chat_tmp = []
render_webvtt_tmp = []
for idx, channel in enumerate(channels):
    found = False
    for user in users_tmp:
        if user["login"].lower() == channel.lower():
            users.append(user)
            render_chat_tmp.append(render_chat[idx])
            render_webvtt_tmp.append(render_webvtt[idx])
            found = True
            break
    if not found:
        print("streamer %s wasn't found, are they banned???" % channel)
render_chat = render_chat_tmp
render_webvtt = render_webvtt_tmp

# now lets loop through each user and make sure we have downloaded
# their most recent VODs and if we have not, we should download them!
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

    # get this stream object, it will have something if the stream is live
    client_helix = twitch.TwitchHelix(client_id=client_id, client_secret=client_secret)
    client_helix.get_oauth()
    stream = client_helix.get_streams(user_ids=[user["id"]])
    stream_is_live = (len(stream) == 1)

    # get the videos for this specific user
    print("getting videos for -> " + user["login"].lower() + " (id " + str(user["id"]) + ")")
    vid_iter = client_helix.get_videos(user_id=user["id"], page_size=100)
    arr_archive = []
    arr_highlight = []
    arr_upload = []
    ct_added = [0, 0, 0]
    seen_first_video = False
    for video in vid_iter:
        # skip the first VOD is they are live
        if not seen_first_video and stream_is_live:
            print("skipping video " + video['id'] + " since stream is live...")
            seen_first_video = True
            continue
        seen_first_video = True
        # else lets process
        # "all", "upload", "archive", "highlight"
        if video['type'] == 'archive' and ct_added[0] < max_videos:
            arr_archive.append({'helix': video})
            ct_added[0] = ct_added[0] + 1
        elif video['type'] == 'highlight' and ct_added[1] < max_videos:
            arr_highlight.append({'helix': video})
            ct_added[1] = ct_added[1] + 1
        elif video['type'] == 'upload' and ct_added[2] < max_videos:
            arr_upload.append({'helix': video})
            ct_added[2] = ct_added[2] + 1

    # nice debug print
    print("\t- found " + str(len(arr_archive)) + " archives")
    print("\t- found " + str(len(arr_highlight)) + " highlights")
    print("\t- found " + str(len(arr_upload)) + " uploads")

    # loop through each archive/VOD and download
    for video in arr_archive:

        # check if we should download any more
        if utils.terminated_requested:
            print('terminate requested, not downloading any more..')
            break

        # DATA: api data of this vod
        t0_start = time.time()
        video_data = {
            'id': video['helix']['id'],
            'user_id': video['helix']['user_id'],
            'user_name': video['helix']['user_name'],
            'title': video['helix']['title'],
            'type': video['helix']['type'],
            'duration': video['helix']['duration'],
            'url': video['helix']['url'],
            'views': video['helix']['view_count'],
            'moments': utils.get_vod_moments(video['helix']['id']),
            'muted_segments': (video['helix']['muted_segments'] if video['helix']['muted_segments'] != None else []),
            'recorded_at': video['helix']['created_at'].strftime('%Y-%m-%dT%H:%M:%SZ'),
            'recorded_at_iso': video['helix']['created_at'].strftime('%Y%m%d T%H%M%SZ')
        }

        # providing a single source for all filename calls in this script, including stripping illegal characters
        filename_format = utils.cleanFilename(str(video_data['recorded_at_iso']) + " - " + str(video['helix']['id']) + " - " + str(video['helix']['title']) + "_" + str(video['helix']['type']))

        # extract what folder we should save into
        # create the folder if it isn't created already
        try:
            date = datetime.strptime(video_data['recorded_at'], '%Y-%m-%dT%H:%M:%SZ')
            export_folder = format(date.year, '02') + "-" + format(date.month, '02') + "/"
        except:
            export_folder = "unknown/"
        if not os.path.exists(path_data + export_folder):
            os.makedirs(path_data + export_folder)

        # VIDEO: check if the file exists
        file_path_info = path_data + export_folder + filename_format + "_info.json"
        print("\t- saving video info: " + file_path_info)
        if not utils.terminated_requested and not os.path.exists(file_path_info):
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_data, file, indent=4)
        elif not utils.terminated_requested:
            print("\t- updating video info: " + file_path_info)
            with open(file_path_info) as f:
                video_info = json.load(f)
            # update moments if failed before
            if len(video_info["moments"]) == 0:
                moments = utils.get_vod_moments(video['helix']['id'])
                if len(moments) != 0:
                    video_info["moments"] = moments
            # finally write to file
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_info, file, indent=4)

        # VIDEO: check if the file exists
        file_path = path_data + export_folder + filename_format + ".mp4"
        print("\t- download video: " + file_path)
        if not utils.terminated_requested and not os.path.exists(file_path):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m VideoDownload' \
                  + ' --id ' + str(video['helix']['id']) + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --temp-path "' + path_temp + '" -o "' + file_path + '"'
            print("CMD: " + str(cmd))
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            # subprocess.Popen(cmd, shell=True).wait()
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # CHAT: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_bad = file_path_chat + ".BAD"
        file_path_chat_tmp = path_temp + str(video['helix']['id']) + "_chat.json"
        print("\t- download chat: " + file_path_chat)
        if not utils.terminated_requested and not os.path.exists(file_path_chat):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatDownload' \
                  + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --id ' + str(video['helix']['id']) + ' --embed-emotes' \
                  + ' -o ' + file_path_chat_tmp
            print("CMD: " + str(cmd))
            # Attempt to download chat log. If the first attempt with emojis embedded fails, try again without emojis. TDCLI will error out
            #   there's issues with downloading emojis. We'd rather download the log without them than fail entirely.
            #
            # If the no-emoji attempt fails as well, we'll assume there's no chat log at all for this video. We'll write a blank .BAD file
            #   to satisfy future file-exists checks.
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait()
            if proc.returncode != 0:
                print("ERR: Chat could not download. It may have some missing emojis we cannot embed. Trying without...")               
                cmd = path_twitch_cli + ' -m ChatDownload' \
                  + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --id ' + str(video['helix']['id']) \
                  + ' -o ' + file_path_chat_tmp
                print("CMD: " + str(cmd))
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc.wait()
                if proc.returncode != 0:
                    print("ERR: Clip has no chat. Either nothing was said or the source VOD is no longer available. Inserting placeholder.")               
                    with open(file_bad, 'w') as fp:
                        fp.write("No chat log for this clip. Either nothing was said or the source VOD is no longer available.")
                else:
                    print("GOOD: File moved")
                    if os.path.exists(file_path_chat_tmp):
                        shutil.move(file_path_chat_tmp, file_path_chat)
            else:
                print("GOOD: File moved")
                if os.path.exists(file_path_chat_tmp):
                    shutil.move(file_path_chat_tmp, file_path_chat)


            if os.path.exists(file_path_chat_tmp):
                shutil.move(file_path_chat_tmp, file_path_chat) 
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # AUDIO-TO-TEXT: check if file exists
        file_path_webvtt = path_data + export_folder + filename_format + ".vtt"
        if not utils.terminated_requested and os.path.exists(file_path) and not os.path.exists(file_path_webvtt) and render_webvtt[idx]:
            print("\t- transcribing: " + file_path_webvtt)
            t0 = time.time()

            # open the model
            SetLogLevel(-1)
            sample_rate = 16000
            model = Model(path_model)
            rec = KaldiRecognizer(model, sample_rate)
            rec.SetWords(True)

            # open ffmpeg pipe stream of the audio file (from video)
            command = ['ffmpeg', '-nostdin', '-loglevel', 'quiet', '-i', file_path,
                       '-ar', str(sample_rate), '-ac', '1', '-f', 's16le', '-']
            # process = subprocess.Popen(command, stdout=subprocess.PIPE)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            results = []
            while True:
                data = process.stdout.read(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    text = rec.Result()
                    results.append(text)
            results.append(rec.FinalResult())

            # convert to standard format
            vtt = WebVTT()
            for i, res in enumerate(results):
                words = json.loads(res).get('result')
                if not words:
                    continue
                for word in words:
                    start = utils.webvtt_time_string(word['start'])
                    end = utils.webvtt_time_string(word['end'])
                    vtt.captions.append(Caption(start, end, word['word']))
            vtt.save(file_path_webvtt)
            print("\t- done in " + str(time.time() - t0) + " seconds")

            # send pushover that this twitch vod is ready to edit
            text = video['helix']['user_name'] + " vod " + str(video['helix']['id']) \
                    + " ready to edit (" + str(int((time.time() - t0_start)/60.0)) + " min to prepare)"
            utils.send_pushover_message(conf, text)

        # RENDER: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_path_render = path_data + export_folder + filename_format + "_chat.mp4"
        file_path_render_tmp = path_temp + str(video['helix']['id']) + "_chat.mp4"
        if not utils.terminated_requested and os.path.exists(file_path_chat) and not os.path.exists(file_path_render) and render_chat[idx]:
            print("\t- rendering chat: " + file_path_render)
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatRender' \
                  + ' -i ' + file_path_chat + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' -h 926 -w 274 --update-rate 0.1 --framerate 60 --font-size 15' \
                  + ' --temp-path "' + path_temp + '" -o ' + file_path_render_tmp
            # subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            subprocess.Popen(cmd, shell=True).wait()
            if os.path.exists(file_path_render_tmp):
                shutil.move(file_path_render_tmp, file_path_render) 
            print("\t- done in " + str(time.time() - t0) + " seconds")

    # loop through each highlight and download
    for video in arr_highlight:

        # check if we should download any more
        if utils.terminated_requested:
            print('terminate requested, not downloading any more..')
            break

        # DATA: api data of this vod
        t0_start = time.time()
        video_data = {
            'id': video['helix']['id'],
            'user_id': video['helix']['user_id'],
            'user_name': video['helix']['user_name'],
            'title': video['helix']['title'],
            'type': video['helix']['type'],
            'duration': video['helix']['duration'],
            'url': video['helix']['url'],
            'views': video['helix']['view_count'],
            'moments': utils.get_vod_moments(video['helix']['id']),
            'muted_segments': (video['helix']['muted_segments'] if video['helix']['muted_segments'] != None else []),
            'recorded_at': video['helix']['created_at'].strftime('%Y-%m-%dT%H:%M:%SZ'),
            'recorded_at_iso': video['helix']['created_at'].strftime('%Y%m%d T%H%M%SZ')
        }

        # providing a single source for all filename calls in this script, including stripping illegal characters
        filename_format = utils.cleanFilename(str(video_data['recorded_at_iso']) + " - " + str(video['helix']['id']) + " - " + str(video['helix']['title']) + "_" + str(video['helix']['type']))

        # extract what folder we should save into
        # create the folder if it isn't created already
        try:
            date = datetime.strptime(video_data['recorded_at'], '%Y-%m-%dT%H:%M:%SZ')
            export_folder = format(date.year, '02') + "-" + format(date.month, '02') + "/"
        except:
            export_folder = "unknown/"
        if not os.path.exists(path_data + export_folder):
            os.makedirs(path_data + export_folder)

        # VIDEO: check if the file exists
        file_path_info = path_data + export_folder + filename_format + "_info.json"
        print("\t- saving video info: " + file_path_info)
        if not utils.terminated_requested and not os.path.exists(file_path_info):
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_data, file, indent=4)
        elif not utils.terminated_requested:
            print("\t- updating video info: " + file_path_info)
            with open(file_path_info) as f:
                video_info = json.load(f)
            # update moments if failed before
            if len(video_info["moments"]) == 0:
                moments = utils.get_vod_moments(video['helix']['id'])
                if len(moments) != 0:
                    video_info["moments"] = moments
            # finally write to file
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_info, file, indent=4)

        # VIDEO: check if the file exists
        file_path = path_data + export_folder + filename_format + ".mp4"
        print("\t- download video: " + file_path)
        if not utils.terminated_requested and not os.path.exists(file_path):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m VideoDownload' \
                  + ' --id ' + str(video['helix']['id']) + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --temp-path "' + path_temp + '" -o "' + file_path + '"'
            print("CMD: " + str(cmd))
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            # subprocess.Popen(cmd, shell=True).wait()
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # CHAT: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_bad = file_path_chat + ".BAD"
        file_path_chat_tmp = path_temp + str(video['helix']['id']) + "_chat.json"
        print("\t- download chat: " + file_path_chat)
        if not utils.terminated_requested and not os.path.exists(file_path_chat):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatDownload' \
                  + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --id ' + str(video['helix']['id']) + ' --embed-emotes' \
                  + ' -o ' + file_path_chat_tmp
            print("CMD: " + str(cmd))
            # Attempt to download chat log. If the first attempt with emojis embedded fails, try again without emojis. TDCLI will error out
            #   there's issues with downloading emojis. We'd rather download the log without them than fail entirely.
            #
            # If the no-emoji attempt fails as well, we'll assume there's no chat log at all for this video. We'll write a blank .BAD file
            #   to satisfy future file-exists checks.
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait()
            if proc.returncode != 0:
                print("ERR: Clip has no chat. Either nothing was said or the source VOD is no longer available. Inserting placeholder.")               
                with open(file_bad, 'w') as fp:
                    fp.write("No chat log for this clip. Either nothing was said or the source VOD is no longer available.")
            else:
                print("GOOD: File moved")
                if os.path.exists(file_path_chat_tmp):
                    shutil.move(file_path_chat_tmp, file_path_chat)
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # AUDIO-TO-TEXT: check if file exists
        file_path_webvtt = path_data + export_folder + filename_format + ".vtt"
        if not utils.terminated_requested and os.path.exists(file_path) and not os.path.exists(file_path_webvtt) and render_webvtt[idx]:
            print("\t- transcribing: " + file_path_webvtt)
            t0 = time.time()

            # open the model
            SetLogLevel(-1)
            sample_rate = 16000
            model = Model(path_model)
            rec = KaldiRecognizer(model, sample_rate)
            rec.SetWords(True)

            # open ffmpeg pipe stream of the audio file (from video)
            command = ['ffmpeg', '-nostdin', '-loglevel', 'quiet', '-i', file_path,
                       '-ar', str(sample_rate), '-ac', '1', '-f', 's16le', '-']
            # process = subprocess.Popen(command, stdout=subprocess.PIPE)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            results = []
            while True:
                data = process.stdout.read(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    text = rec.Result()
                    results.append(text)
            results.append(rec.FinalResult())

            # convert to standard format
            vtt = WebVTT()
            for i, res in enumerate(results):
                words = json.loads(res).get('result')
                if not words:
                    continue
                for word in words:
                    start = utils.webvtt_time_string(word['start'])
                    end = utils.webvtt_time_string(word['end'])
                    vtt.captions.append(Caption(start, end, word['word']))
            vtt.save(file_path_webvtt)
            print("\t- done in " + str(time.time() - t0) + " seconds")

            # send pushover that this twitch vod is ready to edit
            text = video['helix']['user_name'] + " vod " + str(video['helix']['id']) \
                    + " ready to edit (" + str(int((time.time() - t0_start)/60.0)) + " min to prepare)"
            utils.send_pushover_message(conf, text)

        # RENDER: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_path_render = path_data + export_folder + filename_format + "_chat.mp4"
        file_path_render_tmp = path_temp + str(video['helix']['id']) + "_chat.mp4"
        if not utils.terminated_requested and os.path.exists(file_path_chat) and not os.path.exists(file_path_render) and render_chat[idx]:
            print("\t- rendering chat: " + file_path_render)
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatRender' \
                  + ' -i ' + file_path_chat + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' -h 926 -w 274 --update-rate 0.1 --framerate 60 --font-size 15' \
                  + ' --temp-path "' + path_temp + '" -o ' + file_path_render_tmp
            # subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            subprocess.Popen(cmd, shell=True).wait()
            if os.path.exists(file_path_render_tmp):
                shutil.move(file_path_render_tmp, file_path_render) 
            print("\t- done in " + str(time.time() - t0) + " seconds")

    # loop through each highlight and download
    for video in arr_upload:

        # check if we should download any more
        if utils.terminated_requested:
            print('terminate requested, not downloading any more..')
            break

        # DATA: api data of this vod
        t0_start = time.time()
        video_data = {
            'id': video['helix']['id'],
            'user_id': video['helix']['user_id'],
            'user_name': video['helix']['user_name'],
            'title': video['helix']['title'],
            'type': video['helix']['type'],
            'duration': video['helix']['duration'],
            'url': video['helix']['url'],
            'views': video['helix']['view_count'],
            'moments': utils.get_vod_moments(video['helix']['id']),
            'muted_segments': (video['helix']['muted_segments'] if video['helix']['muted_segments'] != None else []),
            'recorded_at': video['helix']['created_at'].strftime('%Y-%m-%dT%H:%M:%SZ'),
            'recorded_at_iso': video['helix']['created_at'].strftime('%Y%m%d T%H%M%SZ')
        }

        # providing a single source for all filename calls in this script, including stripping illegal characters
        filename_format = utils.cleanFilename(str(video_data['recorded_at_iso']) + " - " + str(video['helix']['id']) + " - " + str(video['helix']['title']) + "_" + str(video['helix']['type']))

        # extract what folder we should save into
        # create the folder if it isn't created already
        try:
            date = datetime.strptime(video_data['recorded_at'], '%Y-%m-%dT%H:%M:%SZ')
            export_folder = format(date.year, '02') + "-" + format(date.month, '02') + "/"
        except:
            export_folder = "unknown/"
        if not os.path.exists(path_data + export_folder):
            os.makedirs(path_data + export_folder)

        # VIDEO: check if the file exists
        file_path_info = path_data + export_folder + filename_format + "_info.json"
        print("\t- saving video info: " + file_path_info)
        if not utils.terminated_requested and not os.path.exists(file_path_info):
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_data, file, indent=4)
        elif not utils.terminated_requested:
            print("\t- updating video info: " + file_path_info)
            with open(file_path_info) as f:
                video_info = json.load(f)
            # update moments if failed before
            if len(video_info["moments"]) == 0:
                moments = utils.get_vod_moments(video['helix']['id'])
                if len(moments) != 0:
                    video_info["moments"] = moments
            # finally write to file
            with open(file_path_info, 'w', encoding="utf-8") as file:
                json.dump(video_info, file, indent=4)

        # VIDEO: check if the file exists
        file_path = path_data + export_folder + filename_format + ".mp4"
        print("\t- download video: " + file_path)
        if not utils.terminated_requested and not os.path.exists(file_path):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m VideoDownload' \
                  + ' --id ' + str(video['helix']['id']) + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --temp-path "' + path_temp + '" -o "' + file_path + '"'
            print("CMD: " + str(cmd))
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            # subprocess.Popen(cmd, shell=True).wait()
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # CHAT: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_bad = file_path_chat + ".BAD"
        file_path_chat_tmp = path_temp + str(video['helix']['id']) + "_chat.json"
        print("\t- download chat: " + file_path_chat)
        if not utils.terminated_requested and not os.path.exists(file_path_chat):
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatDownload' \
                  + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --id ' + str(video['helix']['id']) + ' --embed-emotes' \
                  + ' -o ' + file_path_chat_tmp
            print("CMD: " + str(cmd))
            # Attempt to download chat log. If the first attempt with emojis embedded fails, try again without emojis. TDCLI will error out
            #   there's issues with downloading emojis. We'd rather download the log without them than fail entirely.
            #
            # If the no-emoji attempt fails as well, we'll assume there's no chat log at all for this video. We'll write a blank .BAD file
            #   to satisfy future file-exists checks.
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait()
            if proc.returncode != 0:
                print("ERR: Chat could not download. It may have some missing emojis we cannot embed. Trying without...")               
                cmd = path_twitch_cli + ' -m ChatDownload' \
                  + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' --id ' + str(video['helix']['id']) \
                  + ' -o ' + file_path_chat_tmp
                print("CMD: " + str(cmd))
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc.wait()
                if proc.returncode != 0:
                    print("ERR: Clip has no chat. Either nothing was said or the source VOD is no longer available. Inserting placeholder.")               
                    with open(file_bad, 'w') as fp:
                        fp.write("No chat log for this clip. Either nothing was said or the source VOD is no longer available.")
                else:
                    print("GOOD: File moved")
                    if os.path.exists(file_path_chat_tmp):
                        shutil.move(file_path_chat_tmp, file_path_chat)
            else:
                print("GOOD: File moved")
                if os.path.exists(file_path_chat_tmp):
                    shutil.move(file_path_chat_tmp, file_path_chat)
            print("\t- done in " + str(time.time() - t0) + " seconds")

        # AUDIO-TO-TEXT: check if file exists
        file_path_webvtt = path_data + export_folder + filename_format + ".vtt"
        if not utils.terminated_requested and os.path.exists(file_path) and not os.path.exists(file_path_webvtt) and render_webvtt[idx]:
            print("\t- transcribing: " + file_path_webvtt)
            t0 = time.time()

            # open the model
            SetLogLevel(-1)
            sample_rate = 16000
            model = Model(path_model)
            rec = KaldiRecognizer(model, sample_rate)
            rec.SetWords(True)

            # open ffmpeg pipe stream of the audio file (from video)
            command = ['ffmpeg', '-nostdin', '-loglevel', 'quiet', '-i', file_path,
                       '-ar', str(sample_rate), '-ac', '1', '-f', 's16le', '-']
            # process = subprocess.Popen(command, stdout=subprocess.PIPE)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            results = []
            while True:
                data = process.stdout.read(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    text = rec.Result()
                    results.append(text)
            results.append(rec.FinalResult())

            # convert to standard format
            vtt = WebVTT()
            for i, res in enumerate(results):
                words = json.loads(res).get('result')
                if not words:
                    continue
                for word in words:
                    start = utils.webvtt_time_string(word['start'])
                    end = utils.webvtt_time_string(word['end'])
                    vtt.captions.append(Caption(start, end, word['word']))
            vtt.save(file_path_webvtt)
            print("\t- done in " + str(time.time() - t0) + " seconds")

            # send pushover that this twitch vod is ready to edit
            text = video['helix']['user_name'] + " vod " + str(video['helix']['id']) \
                    + " ready to edit (" + str(int((time.time() - t0_start)/60.0)) + " min to prepare)"
            utils.send_pushover_message(conf, text)

        # RENDER: check if the file exists
        file_path_chat = path_data + export_folder + filename_format + "_chat.json"
        file_path_render = path_data + export_folder + filename_format + "_chat.mp4"
        file_path_render_tmp = path_temp + str(video['helix']['id']) + "_chat.mp4"
        if not utils.terminated_requested and os.path.exists(file_path_chat) and not os.path.exists(file_path_render) and render_chat[idx]:
            print("\t- rendering chat: " + file_path_render)
            t0 = time.time()
            cmd = path_twitch_cli + ' -m ChatRender' \
                  + ' -i ' + file_path_chat + ' --ffmpeg-path "' + ffmpeg_path + '"' \
                  + ' -h 926 -w 274 --update-rate 0.1 --framerate 60 --font-size 15' \
                  + ' --temp-path "' + path_temp + '" -o ' + file_path_render_tmp
            # subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
            subprocess.Popen(cmd, shell=True).wait()
            if os.path.exists(file_path_render_tmp):
                shutil.move(file_path_render_tmp, file_path_render) 
            print("\t- done in " + str(time.time() - t0) + " seconds")
