# this is a follow-along script based on the tutorial on youtube regarding
# using the REST API from indeed.com

import os
import hashlib
import base64
import json
from pathlib import Path
from requests_oauthlib  import OAuth2Session

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

from typing import Tuple, List

from user_credentials import client_id, client_secret
from read_data import get_playlists_id

import time
from isodelta


def make_request(url, params):
    # make a brief pause of 1 second before each request
    time.sleep(1)

    try:
        r = session.get(url, params=params)
    except Exception as e:
        raise Exception(e)
    
    if r.status_code == 200:
        return r
    elif r.status_code == 429:
        wait_seconds = 20
        print(f"Rate limited, waiting {wait_seconds} seconds ...")
        time.sleep(wait_seconds)
        make_request(url, params)
    else:
        print('Status code: ', r.status_code)
        raise Exception(r.text)


# 3. PKCE Setup (Required by TIDAL)
def generate_codes() -> Tuple:
    # Generate a cryptographically random string (Code Verifier)
    # todo: how to now this was the step required?
    code_verifier = base64.urlsafe_b64encode(
        os.urandom(40)).decode('utf-8').replace('=', '')
    # Hash it to create the Code Challenge
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()).decode('utf-8').replace('=', '')
    
    return code_verifier, code_challenge


def start_authorizied_session() -> OAuth2Session:

    # params for authorization flow
    scope = ["collection.read", "collection.write", "user.read", "playback", 
            "search.read", "playlists.read", "recommendations.read", 
            "playlists.write", "search.write", "entitlements.read"]

    # creates a OAuth session object
    session = OAuth2Session(
        client_id, 
        redirect_uri="https://www.google.com/", 
        scope=scope,)

    # Get Authorization Link
    # We manually add the PKCE challenge here
    code_verifier, code_challenge = generate_codes()

    # todo: find bettter place for this
    authorization_base_url="https://login.tidal.com/authorize"
    authorization_url, state = session.authorization_url(
        authorization_base_url,
        code_challenge=code_challenge,
        code_challenge_method="S256"
    )

    # follow the link to verify identity
    print(f"Send the user to TIDAL by clicking this link: {authorization_url}")

    # todo: automate this with playwright or selenium?
    redirect_response = input("2. After logging in, paste the FULL URL you were redirected to: ")

    # 6. Exchange Code for Token
    # We must provide the code_verifier we created in step 3
    token = session.fetch_token(
        token_url="https://auth.tidal.com/v1/oauth2/token",
        client_secret=client_secret,
        authorization_response=redirect_response,
        code_verifier=code_verifier 
    )

    # Update the session headers to include the JSON:API requirement. However, I 
    # had to modify the 'accept' and 'content-type' string instead of the one 
    # suggested in their website: 'application/vnd.tidal.v1+json'
    session.headers.update({
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "Authorization": f"Bearer {token['access_token']}",
    })

    return session


def get_attributes_from_track_list(list_of_dict) -> pd.DataFrame:
        # iterate over the list of tracks to grab info
    list_of_tracks = [] # list of dictionaries for each song and key attributes

    for track_dict in list_of_dict:  # iterate over list
        key_attributes = ['title', 'duration', 'popularity']
        track_attributes = track_dict["attributes"]
        track = {attribute: track_attributes[attribute] for attribute in key_attributes}
        list_of_tracks.append(track)
    
    # create a dataframe out of this playlist   
    playlist_df = pd.DataFrame(list_of_tracks)
    playlist_df['playlist_name'] = playlist_name
    return playlist_df

# todo: build this with TDD
def parse_duration(duration: str) -> int:
    pattern = r"PT(?:(\d+)M)?(?:(\d+)S)?"
    match = re.search(duration, pattern)

    if match:
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2) or 0)
        return minutes * 60 + seconds
    return 0


session = start_authorizied_session()

# 7. Retrieve User Information
# Get user info once
me = session.get("https://openapi.tidal.com/v2/users/me").json()
country_code = me["data"]["attributes"]["country"]  # "CO"
user_id = me["data"]["id"]

# the following takes the UUID from a playlist and gets the track ids. 
# from the track ids, we can get the artist, album, popularity score, etc.

base = "https://openapi.tidal.com/v2"

list_of_playlist_id = get_playlists_id(Path('playlists_id.txt'))

# batch fetch the playlists' names
# by adding the "include" parameter, this also includes the tracks of the 
# playlist, so I don't have to make a second request (avoiding rate limits)
# however, TIDAL only sends in packages of 20 tracks
# upon later inspection: adding the tracks here doesn't help much, because
# it doesn't include the attributes of those tracks included, only the ids

playlist_response_batch = session.get(
        f"{base}/playlists", 
        params={"filter[id]": ",".join(list_of_playlist_id),
                "include": "items.tracks"})

playlist_data_list = playlist_response_batch.json()['data']


list_of_playlists_df = []
for playlist_data in playlist_data_list:
    playlist_name = playlist_data['attributes']['name']
    number_of_tracks = playlist_data['attributes']['numberOfItems']

    print(f"Gathering data of playlist {playlist_name!r}, \
          with {number_of_tracks} tracks ...")

    # get the first 20 tracks ids, without having to send a new request
    track_ids = [track['id'] for track in playlist_data['relationships']['items']['data']]

    # the first link to the next batch of tracks
    next_url = f"{base}/{playlist_data['relationships']['items']['links'].get('next')}"
    while len(track_ids) < number_of_tracks:
        # make a new request for the next batch of tracks in the playlist
        r = make_request(
            next_url,
            params={"include": "items.tracks"})

        track_ids.extend([track['id'] for track in r.json()['data']])

        # this request provides in "included" the attributes for those tracks
        # so better to gather here without having to do an additional request
        df = get_attributes_from_track_list(r.json()['included'])
        list_of_playlists_df.append(df)
        # update the url for the next iteration. If this is the last iteration
        # next_url is None, won't be used
        next_url = f"{base}/{r.json()['links'].get('next')}"

    # fetch attributes of the first batch of tracks
    filter_max = 20 # only possible to get 20, otherwise 400
    tracks_r = make_request(
        f"{base}/tracks",
        params={
            "filter[id]": ",".join(track_ids[:filter_max]), 
        }
    )

    # grab track attributes from this request
    df = get_attributes_from_track_list(tracks_r.json()["data"])
    list_of_playlists_df.append(df)

playlists_df = pd.concat(list_of_playlists_df)


# plot results for popularity scores

sns.boxplot(data=playlists_df,
            x='popularity', y='playlist_name',
            width=0.25, color="0.8", saturation=0.5)

# swarmplot is problematic for large number of points
# sns.swarmplot(data=playlists_df,
#               x='popularity', y='playlist_name')

plt.xlim([0,1])
plt.xlabel('Popularity Score')
#plt.ylabel(rotation=0)
plt.tight_layout()
plt.show()
