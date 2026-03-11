
import os
import sys
import json
import logging

# Añadir el directorio actual al path para importar locales
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.youtube_api import YouTubeAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fallback():
    api = YouTubeAPI(api_key="SIMULATED_QUOTA_EXCEEDED")
    # Canal de TNT Sports Chile (ID de la whitelist)
    channel_id = "UChCovZlgNh2x6Z57MJ5fhFw"
    
    logger.info(f"Probando fallback para canal: {channel_id}")
    videos = api.get_latest_videos_no_api(channel_id, count=2)
    
    if videos:
        print(f"✅ Se encontraron {len(videos)} videos:")
        for v in videos:
            print(f"  - [{v['id']['videoId']}] {v['snippet']['title']}")
        
        # Verificar campos requeridos
        v = videos[0]
        required = ["id", "snippet"]
        required_snippet = ["title", "description", "channelId", "channelTitle", "publishedAt"]
        
        missing = [f for f in required if f not in v]
        missing_s = [f for f in required_snippet if f not in v.get("snippet", {})]
        
        if not missing and not missing_s:
            print("✅ Formato de datos validado.")
        else:
            print(f"❌ Faltan campos: {missing} {missing_s}")
    else:
        print("❌ No se encontraron videos con el fallback.")

if __name__ == "__main__":
    test_fallback()
