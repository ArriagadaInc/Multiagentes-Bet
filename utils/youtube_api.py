import os
import requests
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"

class YouTubeAPI:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.api_key_alt = os.getenv("YOUTUBE_API_KEY_ALTERNATIVA")
        if not self.api_key:
            logger.warning("YOUTUBE_API_KEY no configurada. Las llamadas a YouTube fallarán.")

    def _request(self, url: str, params: Dict[str, Any], key: str) -> requests.Response:
        params["key"] = key
        return requests.get(url, params=params, timeout=15)
    def _extract_error_info(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return ""
        err = data.get("error", {}) if isinstance(data, dict) else {}
        message = err.get("message")
        reason = None
        errors = err.get("errors")
        if isinstance(errors, list) and errors:
            reason = errors[0].get("reason")
        parts = []
        if reason:
            parts.append(f"reason={reason}")
        if message:
            parts.append(f"message={message}")
        return ", ".join(parts)


    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Realiza una petici?n GET a la API de YouTube."""
        if not self.api_key:
            return {"error": "API Key missing"}
        
        url = f"{YOUTUBE_API_URL}/{endpoint}"
        
        try:
            response = self._request(url, dict(params), self.api_key)
            if response.status_code == 403 and self.api_key_alt and self.api_key_alt != self.api_key:
                info = self._extract_error_info(response)
                suffix = f" ({info})" if info else ""
                logger.warning(
                    f"Error 403 en endpoint {endpoint}{suffix}. "
                    "Cambiando a YOUTUBE_API_KEY_ALTERNATIVA para el resto de llamadas."
                )
                self.api_key = self.api_key_alt
                response = self._request(url, dict(params), self.api_key)
            if response.status_code == 403:
                info = self._extract_error_info(response)
                suffix = f" ({info})" if info else ""
                logger.error(f"Error 403 en endpoint {endpoint}{suffix}.")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en llamada a YouTube ({endpoint}): {e}")
            return {"error": str(e)}

    def search_videos(
        self,
        query: str,
        published_after: str,
        max_results: int = 10,
        channel_id: Optional[str] = None,
        language: Optional[str] = None,
        region_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca videos en YouTube basándose en una query y fecha.
        Endpoint: /search (type=video)
        Costo: 100 unidades
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "publishedAfter": published_after,
            "maxResults": max_results,
            "order": "relevance",
            "relevanceLanguage": language or os.getenv("JOURNALIST_LANGUAGE", "es"),
        }
        final_region = region_code if region_code is not None else os.getenv("JOURNALIST_REGION_CODE", "CL")
        if final_region:
            params["regionCode"] = final_region
        if channel_id:
            params["channelId"] = channel_id
            
        data = self._get("search", params)
        return data.get("items", [])

    def get_video_stats(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene métricas (vistas, likes) de videos específicos.
        Endpoint: /videos
        Costo: 1 unidad por lote de 50
        """
        if not video_ids:
            return {}
            
        results = {}
        # La API de YouTube permite hasta 50 IDs por petición
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            params = {
                "part": "statistics,snippet",
                "id": ",".join(chunk)
            }
            data = self._get("videos", params)
            items = data.get("items", [])
            for item in items:
                results[item["id"]] = item
        
        return results

    def get_channel_stats(self, channel_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene métricas de canales (suscriptores).
        Endpoint: /channels
        Costo: 1 unidad por lote de 50
        """
        if not channel_ids:
            return {}
            
        results = {}
        for i in range(0, len(channel_ids), 50):
            chunk = channel_ids[i:i + 50]
            params = {
                "part": "statistics,snippet",
                "id": ",".join(chunk)
            }
            data = self._get("channels", params)
            items = data.get("items", [])
            for item in items:
                results[item["id"]] = item
        
        return results
    def get_playlist_items(self, playlist_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Obtiene los items de una playlist (como la de 'Uploads' de un canal).
        Costo: 1 unidad (vs 100 de search)
        """
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": max_results
        }
        data = self._get("playlistItems", params)
        return data.get("items", [])

    def get_uploads_playlist_id(self, channel_id: str) -> Optional[str]:
        """Obtiene el ID de la playlist de Uploads de un canal (UC... -> UU...)."""
        if channel_id.startswith("UC"):
            return "UU" + channel_id[2:]
        return None

    def get_latest_videos_no_api(self, channel_id: str, count: int = 2) -> List[Dict[str, Any]]:
        """
        Fallback extremo: Obtiene los últimos videos de un canal usando yt-dlp.
        No consume cuota de API de YouTube.
        """
        import subprocess
        import json
        
        logger.info(f"YOUTUBE FALLBACK: Obteniendo {count} videos de {channel_id} usando yt-dlp")
        
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
        cmd = [
            "yt-dlp",
            "--playlist-end", str(count),
            "--dump-json",
            "--flat-playlist",
            "--quiet",
            "--no-warnings",
            url
        ]
        
        items = []
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if not line.strip(): continue
                data = json.loads(line)
                
                # Mapear al formato esperado por el resto del sistema
                items.append({
                    "id": {"videoId": data.get("id")},
                    "snippet": {
                        "title": data.get("title", ""),
                        "description": data.get("description", ""),
                        "channelId": channel_id,
                        "channelTitle": data.get("uploader", "Whitelist Channel"),
                        "publishedAt": datetime.fromtimestamp(data.get("timestamp", 0), timezone.utc).isoformat() if data.get("timestamp") else "2026-01-01T00:00:00Z"
                    }
                })
        except Exception as e:
            logger.error(f"Error fatal en fallback yt-dlp para {channel_id}: {e}")
            
        return items
