
import os
import json
import requests
from dotenv import load_dotenv
from utils.youtube_api import YouTubeAPI

load_dotenv()

def find_channel_id(handle):
    api = YouTubeAPI()
    try:
        # Search for the channel specifically
        params = {
            "part": "snippet",
            "q": handle,
            "type": "channel",
            "maxResults": 1
        }
        res = api._get("search", params)
        
        items = res.get("items", [])
        if items:
            channel_id = items[0]["id"]["channelId"]
            title = items[0]["snippet"]["title"]
            print(f"Found: {handle} -> {channel_id} ({title})")
            return channel_id
        else:
            print(f"Not found: {handle}")
            return None
    except Exception as e:
        print(f"Error finding {handle}: {e}")
        return None

if __name__ == "__main__":
    handles = ["@loscampeones", "@diarioas", "@espnfans", "@ThonyBet"]
    results = {}
    for h in handles:
        cid = find_channel_id(h)
        if cid:
            results[h] = cid
            
    print("\nSummary for .env:")
    print(",".join(results.values()))
