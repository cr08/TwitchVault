import configparser
import json
import requests

configfile = "config.ini"

config = configparser.ConfigParser()
config.read(configfile)

oauth_url = "https://id.twitch.tv/oauth2/token"
clientid = config.get('twitch','clientid')
secret = config.get('twitch','secret')

r1 = requests.post(url = oauth_url, data={'client_id':clientid,'client_secret':secret,'grant_type':"client_credentials"})

token = r1.json()["access_token"]

headers = {
    'Client-ID': clientid,
    'Authorization': 'Bearer ' + token
}

vod_chans = config.items('vod_chan')
for key, value in vod_chans:

    stream = requests.get('https://api.twitch.tv/helix/streams?user_id=' + value, headers=headers)
    streamj = stream.json()

    videos = requests.get('https://api.twitch.tv/helix/videos?user_id=' + value + '&period=week', headers=headers)
    videosj = videos.json()

    # Determine if stream is currently live so we can omit it's ID from the VOD list so not to download a partial stream
    if streamj['data']:
        print('Stream: ' + streamj['data'][0]['id'])

        print('Videos: ' + videosj['data'][0]['stream_id'])

    else:
        print('Stream: Offline')



#    streams = client.get_streams(user_ids=value)
#    json.loads(streams)['data'][0]['id']
#    if streamsj['data']:
#        print(x)

#    videos = client.get_videos(user_id=value,period="week")

#    print(videos)

#clip_chans = config.items('clip_chan')
#for key, value in clip_chans:
#    print(key)
#    print(value)





