
import os
import json
from dotenv import load_dotenv
from utils.youtube_api import YouTubeAPI

load_dotenv()

def find_channel_id(handle):
    api = YouTubeAPI()
    try:
        params = {
            "part": "snippet",
            "q": handle,
            "type": "channel",
            "maxResults": 1
        }
        res = api._get("search", params)
        if "error" in res:
            print(f"Error finding {handle}: {res['error']}")
            return None
            
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
    # Canales encontrados en la búsqueda dinámica que parecen buenos
    handles = [
        "@AtleticoStats", 
        "@HAJJBALL", 
        "@AsistenciaDeGol", 
        "@PaseAtrasTV",
        "@LilVitu",
        "@TipsterChat",
        "@PuebloJuve",
        "@MaestroPanenka",
        "@SirRayAnalysis"
    ]
    results = {}
    for h in handles:
        cid = find_channel_id(h)
        if cid:
            results[h] = cid
            
    print("\nRecommended for .env UCL Whitelist (Append these):")
    print(",".join(results.values()))
