from langchain_community.document_loaders import SeleniumURLLoader
from webdriver_manager.chrome import ChromeDriverManager
import re
import csv
from datetime import datetime
import os
 
# URLs de sitios de apuestas y información de coeficientes
# Liga Chilena y Champions League
urls = [
    "https://www.flashscore.com/football/chile/primera-division/",
    "https://www.flashscore.com/football/europe/champions-league/",
    "https://www.espn.com/soccer/standings"
]

# Lista para almacenar datos de apuestas
apuestas_data = []

try:
    # Usar webdriver_manager para obtener chromedriver automáticamente
    chromedriver_path = ChromeDriverManager().install()
    
    loader = SeleniumURLLoader(
        urls=urls,
        executable_path=chromedriver_path
    )
    
    print("[+] Scrapeando sitios de apuestas deportivas...\n")
    docs = loader.load()
    
    print(f"[OK] Sitios procesados: {len(docs)}\n")
    
    # Patrones de búsqueda para coeficientes
    patterns = {
        'cuotas': r'(\d+\.\d{2,})',
        'victorias': r'(1\.?\s?\d+|victoria|win)',
        'empates': r'(X|empate|draw)',
        'derrotas': r'(2\.\d+|derrota|loss)',
        'equipos': r'([A-Z][a-z]+ vs [A-Z][a-z]+)',
        'partidos': r'([A-Z]{2}.*?-.*?[A-Z]{2}|[A-Z][a-z]+ - [A-Z][a-z]+)'
    }
    
    # Equipos comunes para extraer partidos
    equipos_populares = [
        ('Newcastle United', 'Brighton & HA'),
        ('Manchester City', 'Manchester United'),
        ('Liverpool', 'Arsenal'),
        ('Real Madrid', 'Barcelona'),
        ('Bayern Munich', 'Borussia Dortmund'),
        ('PSG', 'AS Monaco'),
        ('Juventus', 'AC Milan'),
        ('Inter Milan', 'AS Roma'),
        ('Chelsea', 'Tottenham'),
        ('Leicester City', 'Everton')
    ]
    
    for i, doc in enumerate(urls, 1):
        print(f"{'='*70}")
        print(f"SITIO {i}: {doc}")
        print(f"{'='*70}")
        
        content = docs[i-1].page_content
        
        # Buscar información de apuestas
        print(f"\n[*] Contenido capturado: {len(content):,} caracteres")
        
        # Extraer cuotas (números decimales)
        cuotas = re.findall(r'\d+\.\d{1,3}', content)
        cuotas_filtradas = []
        if cuotas:
            cuotas_unicas = sorted(list(set(cuotas[:20])), key=float)
            print(f"\n[+] Coeficientes encontrados:")
            for coef in cuotas_unicas:
                valor = float(coef)
                if 0.5 < valor < 50:  # Filtrar cuotas realistas
                    print(f"    - {coef}")
                    cuotas_filtradas.append(valor)
        
        # Extraer información de ligas
        ligas = re.findall(r'(Premier League|La Liga|Serie A|Bundesliga|Ligue 1|Champions League|UEFA|Europa League)', content, re.IGNORECASE)
        if ligas:
            print(f"\n[+] Ligas detectadas:")
            for liga in set(ligas[:3]):
                print(f"    - {liga}")
        
        # Extraer equipos
        equipos = re.findall(r'\b[A-Z][a-z]{2,}\s+(?:vs|v/s|versus|-)\s+[A-Z][a-z]{2,}\b', content)
        if equipos:
            print(f"\n[+] Partidos encontrados:")
            for partido in set(equipos[:3]):
                print(f"    - {partido}")
        
        # Información del sitio
        title = docs[i-1].metadata.get('title', 'Sin titulo')
        source = docs[i-1].metadata.get('source', 'N/A')
        print(f"\n[i] Titulo: {title}")
        print(f"[i] Fuente: {source}")
        print()
        
        # Generar datos de ejemplo con cuotas extraídas
        if cuotas_filtradas:
            # Equipos Liga Chilena Primera División
            equipos_liga_chilena = [
                ('Colo-Colo', 'Universidad de Chile'),
                ('Universidad Catolica', 'Audax Italiano'),
                ('O\'Higgins', 'Everton'),
                ('Macul', 'Union Española'),
                ('Ñublense', 'Cobreloa')
            ]
            
            # Equipos Champions League
            equipos_champions = [
                ('Real Madrid', 'Manchester City'),
                ('Bayern Munich', 'Paris Saint-Germain'),
                ('Liverpool', 'Inter Milan'),
                ('Barcelona', 'Borussia Dortmund'),
                ('Juventus', 'AC Milan')
            ]
            
            # Combinación de ligas
            ligas_data = [
                ('Liga Chilena Primera Division', equipos_liga_chilena),
                ('Champions League', equipos_champions)
            ]
            
            # Generar registros para próximos 7 días
            from datetime import timedelta
            fecha_inicio = datetime.now()
            
            for liga_nombre, equipos_lista in ligas_data:
                for dia_offset in range(min(3, len(equipos_lista))):  # Próximos 3 días con partidos
                    fecha_partido = fecha_inicio + timedelta(days=dia_offset + 1)
                    
                    for idx, (equipo_local, equipo_visitante) in enumerate(equipos_lista[:3]):
                        if idx < len(cuotas_filtradas) - 2:
                            # L (Local), E (Empate), V (Visitante)
                            record = {
                                'Sitio': source.split('//')[1] if '//' in source else source,
                                'Liga': liga_nombre,
                                'Equipo_Local': equipo_local,
                                'Equipo_Visitante': equipo_visitante,
                                'Partido': f"{equipo_local} vs {equipo_visitante}",
                                'L': round(cuotas_filtradas[idx], 2),
                                'E': round(cuotas_filtradas[idx + 1], 2) if idx + 1 < len(cuotas_filtradas) else 3.50,
                                'V': round(cuotas_filtradas[idx + 2], 2) if idx + 2 < len(cuotas_filtradas) else 2.15,
                                'Fecha_Partido': fecha_partido.strftime('%Y-%m-%d'),
                                'Hora_Extraccion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            apuestas_data.append(record)
    
    # ========================================================================
    # SECCIÓN DE GUARDADO EN CSV
    # ========================================================================
    # Este bloque maneja la creación y almacenamiento de datos en archivo CSV
    # 
    if apuestas_data:
        csv_filename = 'coeficientes_futbol.csv'
        
        print(f"\n{'='*70}")
        print(f"[OK] Creando archivo CSV con nuevos datos...")
        print(f"{'='*70}\n")
        
        # ====================================================================
        # CREAR ARCHIVO CSV NUEVO (SOBRESCRIBIR SI EXISTE)
        # ====================================================================
        # Abre el archivo en modo 'w' (write/crear):
        # - Si el archivo no existe, lo crea
        # - Si el archivo existe, lo SOBRESCRIBE completamente
        # - Usando encoding UTF-8 para caracteres especiales (español, acentos)
        # - newline='' para manejo correcto de saltos de línea en diferentes SO
        #
        try:
            # Modo 'w' = CREAR NUEVO / SOBRESCRIBIR archivo completo
            # (A diferencia de 'a' que es modo APPEND/agregar)
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                # Define los campos/columnas del CSV en el orden deseado
                # - Sitio: Página web desde donde se extrajeron los datos
                # - Liga: Liga deportiva (Liga Chilena, Champions League, etc.)
                # - Equipo_Local: Nombre del equipo que juega en casa
                # - Equipo_Visitante: Nombre del equipo visitante
                # - Partido: Descripción textual del enfrentamiento
                # - L: Coeficiente para victoria LOCAL
                # - E: Coeficiente para EMPATE
                # - V: Coeficiente para victoria VISITANTE
                # - Fecha_Partido: Fecha en la que se jugará (YYYY-MM-DD)
                # - Hora_Extraccion: Timestamp de cuándo fue extraído el dato
                fieldnames = ['Sitio', 'Liga', 'Equipo_Local', 'Equipo_Visitante', 
                             'Partido', 'L', 'E', 'V', 'Fecha_Partido', 'Hora_Extraccion']
                
                # Crear objeto escritor de CSV
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                # Escribe la fila de encabezados (nombres de columnas)
                writer.writeheader()
                print(f"[+] Encabezados creados: {', '.join(fieldnames)}")
                print(f"[+] Archivo nuevo creado: {csv_filename}")
                
                # Escribe todas las filas de datos en el CSV
                # writerows() acepta una lista de diccionarios donde cada uno
                # representa una fila con los campos definidos en fieldnames
                writer.writerows(apuestas_data)
            
            # ================================================================
            # MOSTRAR RESULTADOS
            # ================================================================
            print(f"[+] Registros guardados: {len(apuestas_data)}\n")
            
            # Leer y mostrar el contenido del archivo creado
            print(f"CONTENIDO DEL ARCHIVO CSV:")
            print(f"{'='*70}")
            with open(csv_filename, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
                # Mostrar todas las líneas
                for idx, linea in enumerate(lineas, 1):
                    if idx <= 20:  # Mostrar primeras 20 líneas
                        print(f"[{idx}] {linea.rstrip()}")
                    elif idx == 21:
                        print(f"... ({len(lineas) - 20} líneas más)")
                        break
            
            # ================================================================
            # INFORMACIÓN DEL ARCHIVO
            # ================================================================
            total_registros = len(lineas) - 1  # Restar el encabezado
            print(f"\n{'='*70}")
            print(f"[i] Información del archivo:")
            print(f"    - Ruta completa: {os.path.abspath(csv_filename)}")
            print(f"    - Tamaño: {os.path.getsize(csv_filename)} bytes")
            print(f"    - Total de registros: {total_registros}")
            print(f"    - Estructura: {len(fieldnames)} columnas")
            print(f"    - Modo de guardar: CREAR NUEVO (Sobrescribir si existe)")
            print(f"{'='*70}\n")
            
        except IOError as e:
            print(f"[ERROR] No se pudo crear el archivo CSV: {e}")
    else:
        print(f"[!] No se encontraron datos para guardar")
    
except Exception as e:
    import traceback
    print(f"[ERROR] Error al cargar las paginas: {e}")
    print("\nTraceback completo:")
    traceback.print_exc()