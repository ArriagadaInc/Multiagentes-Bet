from youtube_transcript_api import YouTubeTranscriptApi
import re
from collections import Counter
import yt_dlp

# Cargar transcripción de un video educativo
video_url = "https://www.youtube.com/watch?v=SFzyuGpUGx0"
video_id = video_url.split("v=")[1]

# Lista de idiomas en orden de preferencia
preferred_languages = ['es', 'en', 'fr', 'de', 'pt', 'it', 'ja', 'zh', 'ko']

try:
    # Obtener información del video (título y canal)
    print("=== INFORMACIÓN DEL VIDEO ===")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        titulo = info.get('title', 'N/A')
        canal = info.get('uploader', 'N/A')
        duracion = info.get('duration', 0)
        fecha = info.get('upload_date', 'N/A')
        vistas = info.get('view_count', 'N/A')
    
    print(f"Título: {titulo}")
    print(f"Canal: {canal}")
    print(f"Duración: {duracion // 60} minutos {duracion % 60} segundos")
    if fecha != 'N/A':
        fecha_formateada = f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"
        print(f"Fecha de publicación: {fecha_formateada}")
    print(f"Vistas: {vistas:,}" if isinstance(vistas, int) else f"Vistas: {vistas}")
    print()
    
    # Intentar obtener transcripción en los idiomas preferidos
    transcript_data = None
    used_language = None
    
    for lang in preferred_languages:
        try:
            # Crear instancia de la API e intentar obtener transcripción
            transcript_data = YouTubeTranscriptApi().fetch(video_id, languages=[lang])
            used_language = lang
            break
        except:
            # Si no está disponible en este idioma, intentar el siguiente
            continue
    
    if transcript_data is None:
        print("Error: No hay transcripción disponible en ninguno de los idiomas solicitados")
        print(f"Idiomas intentados: {preferred_languages}")
        exit()
    
    print("=== INFORMACIÓN DE LA TRANSCRIPCIÓN ===")
    print(f"Idioma utilizado: {used_language}")
    print(f"Número de segmentos: {len(transcript_data)}")
    print()
    
    # Acceder al texto de transcripción
    transcript_text = " ".join([item.text for item in transcript_data])
    
    print("=== ANÁLISIS DE TRANSCRIPCIÓN ===")
    print(f"Longitud de transcripción: {len(transcript_text):,} caracteres")
    print(f"Palabras aproximadas: {len(transcript_text.split()):,}")
    
    # Extraer temas principales (palabras frecuentes)
    words = re.findall(r'\b[a-záéíóúña-z]{4,}\b', transcript_text.lower())
    common_words = Counter(words).most_common(10)
    
    print("\nPalabras más frecuentes:")
    for word, count in common_words:
        print(f"  {word}: {count} veces")
        
    print(f"\nPrimeros 500 caracteres:")
    print(transcript_text[:500] + "...")
    
except Exception as e:
    import traceback
    print(f"Error al cargar el video: {e}")
    print("\nTraceback completo:")
    traceback.print_exc()