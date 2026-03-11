import os
import json
from dotenv import load_dotenv
from utils.youtube_api import YouTubeAPI

def test():
    load_dotenv()
    api = YouTubeAPI()
    
    # Canal ThonyBet
    channel_id = "UCwSBxd6t6RVZ5Y0QrHR8jTg"
    playlist_id = api.get_uploads_playlist_id(channel_id)
    
    print(f"Probando playlistItems para {playlist_id}...")
    items = api.get_playlist_items(playlist_id, max_results=5)
    
    if isinstance(items, list):
        print(f"Éxito: {len(items)} items encontrados.")
        for item in items:
            print(f" - {item['snippet']['title']}")
    else:
        print(f"Fallo o vacío: {items}")

if __name__ == "__main__":
    test()
