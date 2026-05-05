"""
scripts/importar_masivo.py
SIDEC — Importación masiva organizada por empleado / año / mes
==============================================================

ESTRUCTURA DE CARPETAS ESPERADA:
    C:/Instrumentos/
    ├── pedro_garcia/          ← nombre clave del empleado
    │   ├── 2014/
    │   │   ├── 01_enero/
    │   │   │   ├── cert_001.xlsx
    │   │   │   └── cert_002.xlsx
    │   │   └── 02_febrero/
    │   ├── 2015/
    │   └── ...hasta 2022 (año que renunció)
    ├── maria_lopez/
    │   ├── 2018/
    │   └── 2026/
    └── laboratorio/           ← carpeta general sin empleado específico
        └── 2025/

TAMBIÉN ACEPTA estructura plana:
    C:/Instrumentos/2017/enero/archivo.xlsx
    C:/Instrumentos/2017/archivo.xlsx
    C:/Instrumentos/archivo.xlsx

FORMATOS SOPORTADOS: .xlsx, .xls, .pdf  (Word y PPT próximamente)

USO:
    pip install pandas openpyxl psycopg2-binary tqdm colorama pdfplumber
    python importar_masivo.py
    python importar_masivo.py --carpeta "C:/Instrumentos/pedro_garcia" --empleado pedro_garcia
    python importar_masivo.py --solo-escanear     ← solo muestra qué encontraría sin importar
    python importar_masivo.py --anio 2017         ← solo importa un año específico
"""

import os
import sys
import argparse
import re
import json
import logging
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import execute_values
    TIENE_DB = True
except ImportError:
    TIENE_DB = False
    print("⚠ psycopg2 no encontrado. Ejecuta desde el venv: venv/Scripts/python.exe")
    print("  Continuando en modo solo-escaneo...")

# Módulo de extracción específico SIDEC
try:
    from extraer_pdf_sidec import extraer_certificado_sidec, es_certificado_sidec as _es_cert_sidec
    TIENE_EXTRACTOR = True
except ImportError:
    TIENE_EXTRACTOR = False

# ── Librerías opcionales (instaladas si existen) ─────────────
try:
    import openpyxl
    TIENE_XLSX = True
except ImportError:
    TIENE_XLSX = False
    print("⚠ openpyxl no instalado. Instala con: pip install openpyxl")

try:
    import pdfplumber
    TIENE_PDF = True
except ImportError:
    TIENE_PDF = False
    print("⚠ pdfplumber no instalado. PDFs no se procesarán. pip install pdfplumber")

try:
    from tqdm import tqdm
    TIENE_TQDM = True
except ImportError:
    TIENE_TQDM = False
    tqdm = lambda x, **kw: x

try:
    from colorama import Fore, Style, init as cinit
    cinit(autoreset=True)
    OK   = Fore.GREEN  + "✅"
    WARN = Fore.YELLOW + "⚠ "
    ERR  = Fore.RED    + "❌"
    INFO = Fore.CYAN   + "ℹ "
    RST  = Style.RESET_ALL
except ImportError:
    OK = "✅"; WARN = "⚠ "; ERR = "❌"; INFO = "ℹ "; RST = ""

# ============================================================
# CONFIGURACIÓN
# ============================================================
DB_CONFIG = {
    'host':     os.getenv('DB_HOST',     'localhost'),
    'port':     int(os.getenv('DB_PORT', 5432)),
    'dbname':   os.getenv('DB_NAME',     'sidec_db'),
    'user':     os.getenv('DB_USER',     'postgres'),
    'password': os.getenv('DB_PASSWORD', 'casamelon'),
}

# Carpeta raíz donde están todos los empleados/años
CARPETA_RAIZ = r'C:\Instrumentos'

# Años a importar (2015 hasta 2030, agrega más si necesitas)
ANIOS_VALIDOS = set(range(2015, 2031))

# Insertar en lotes de N registros
CHUNK_SIZE = 500

# Tipos de archivo soportados
EXTENSIONES_EXCEL = {'.xlsx', '.xls'}
EXTENSIONES_PDF   = {'.pdf'}
EXTENSIONES_SKIP  = {'.tmp', '.bak', '.doc', '.docx', '.ppt', '.pptx'}  # por ahora

# ============================================================
# LOGGER
# ============================================================
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f'importacion_{ts}.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# DETECCIÓN: empleado / año / mes desde la ruta
# ============================================================

# Meses en español para normalización
MESES_ES = {
    '01': 'enero', '02': 'febrero', '03': 'marzo', '04': 'abril',
    '05': 'mayo',  '06': 'junio',   '07': 'julio', '08': 'agosto',
    '09': 'septiembre', '10': 'octubre', '11': 'noviembre', '12': 'diciembre',
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05',
    'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10',
    'nov': '11', 'dec': '12',
}

def extraer_contexto_ruta(ruta_archivo: str, carpeta_raiz: str) -> dict:
    """
    Analiza la ruta del archivo para detectar empleado, año y mes.

    Ejemplos de rutas que entiende:
      .../pedro_garcia/2017/03_marzo/cert.xlsx  → empleado=pedro_garcia, año=2017, mes=03
      .../laboratorio/2019/cert.xlsx            → empleado=laboratorio, año=2019
      .../2020/febrero/cert.xlsx                → año=2020, mes=02
      .../2018/cert.xlsx                        → año=2018
    """
    ctx = {'empleado': None, 'anio': None, 'mes': None, 'mes_nombre': None}

    # Normalizar separadores
    ruta = Path(ruta_archivo)
    partes = list(ruta.parts)

    # Buscar año en las partes de la ruta
    for i, parte in enumerate(partes):
        # ¿Es un año válido? (2015-2030)
        if re.fullmatch(r'20[1-3]\d', parte):
            ctx['anio'] = int(parte)

            # La parte antes del año puede ser el empleado
            if i > 0:
                posible_empleado = partes[i - 1]
                # Verificar que no sea la carpeta raíz ni un disco
                raiz_norm = str(Path(carpeta_raiz).name).lower()
                if (posible_empleado.lower() not in {'instrumentos', raiz_norm}
                        and not re.fullmatch(r'[A-Za-z]:\\', posible_empleado)
                        and len(posible_empleado) > 2):
                    ctx['empleado'] = posible_empleado.lower().replace(' ', '_')

            # La parte después del año puede ser el mes
            if i + 1 < len(partes):
                posible_mes = partes[i + 1].lower()
                # Quitar prefijos numéricos como "03_", "3-", etc.
                posible_mes_limpio = re.sub(r'^\d{1,2}[_\-\s]?', '', posible_mes).strip()
                num_mes = re.match(r'^(\d{1,2})', partes[i + 1])

                if posible_mes_limpio in MESES_ES:
                    ctx['mes_nombre'] = posible_mes_limpio
                    ctx['mes'] = MESES_ES[posible_mes_limpio]
                elif num_mes:
                    num = num_mes.group(1).zfill(2)
                    if num in MESES_ES:
                        ctx['mes'] = num
                        ctx['mes_nombre'] = MESES_ES[num]
            break

    # Si no encontramos año en la ruta, intentar desde el nombre del archivo
    if not ctx['anio']:
        nombre = ruta.stem
        match_anio = re.search(r'20[1-3]\d', nombre)
        if match_anio:
            ctx['anio'] = int(match_anio.group())

    return ctx


def identificar_tipo_archivo(ruta: str) -> str:
    """Devuelve 'excel', 'pdf', 'skip' o 'desconocido'."""
    ext = Path(ruta).suffix.lower()
    if ext in EXTENSIONES_EXCEL:
        return 'excel'
    if ext in EXTENSIONES_PDF:
        return 'pdf'
    if ext in EXTENSIONES_SKIP:
        return 'skip'
    return 'desconocido'


# ============================================================
# EXTRACCIÓN DESDE EXCEL (misma lógica que importar.py original)
# ============================================================
def buscar_valor_fila(hoja, texto_clave):
    for fila in hoja.iter_rows():
        clave = None
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str) and texto_clave.lower() in celda.value.lower():
                    clave = celda; break
            except: continue
        if clave:
            for c in fila:
                try:
                    if c != clave and c.value:
                        return str(c.value).strip()
                except: continue
    return None

def buscar_valor_relativo(hoja, texto_clave, df=0, dc=1):
    for fila in hoja.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str) and texto_clave.lower() in celda.value.lower():
                    val = hoja.cell(row=celda.row + df, column=celda.column + dc).value
                    if val: return str(val).strip()
            except: continue
    return None

def obtener_hoja_portada(wb):
    for nombre in wb.sheetnames:
        if 'portada' in nombre.lower():
            return wb[nombre]
    return wb.active  # fallback a la primera hoja

def limpiar_fecha(valor):
    if not valor: return None
    if isinstance(valor, datetime): return valor.date()
    formatos = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%Y%m%d']
    for fmt in formatos:
        try: return datetime.strptime(str(valor).strip(), fmt).date()
        except: continue
    return None

def extraer_excel(ruta_archivo: str) -> tuple:
    """Retorna (dict_datos, error_str_o_None)"""
    if not TIENE_XLSX:
        return None, "openpyxl no instalado"
    try:
        wb = openpyxl.load_workbook(ruta_archivo, data_only=True)
        ws = obtener_hoja_portada(wb)

        fecha_emision     = limpiar_fecha(buscar_valor_fila(ws, "Fecha de emisión"))
        fecha_recepcion   = limpiar_fecha(buscar_valor_fila(ws, "Fecha de recepción"))
        fecha_calibracion = limpiar_fecha(buscar_valor_fila(ws, "Fecha de calibración"))

        return {
            "numero_informe":          buscar_valor_relativo(ws, "Hoja 1 de 2", df=1, dc=0),
            "nombre_cliente":          buscar_valor_fila(ws, "Nombre del cliente"),
            "direccion":               buscar_valor_fila(ws, "Dirección"),
            "atencion_a":              buscar_valor_fila(ws, "Atención a"),
            "descripcion_instrumento": buscar_valor_fila(ws, "Descripción del instrumento"),
            "alcance":                 buscar_valor_fila(ws, "Alcance"),
            "numero_serie":            buscar_valor_relativo(ws, "No. de serie", df=0, dc=2),
            "identificacion":          buscar_valor_fila(ws, "Identificación"),
            "modelo":                  buscar_valor_fila(ws, "Modelo"),
            "marca":                   buscar_valor_fila(ws, "Marca"),
            "magnitud_evaluada":       buscar_valor_fila(ws, "Magnitud evaluada"),
            "resultado_calibracion":   buscar_valor_fila(ws, "Resultado de calibración"),
            "incertidumbre":           buscar_valor_fila(ws, "Incertidumbre"),
            "temperatura":             buscar_valor_fila(ws, "Temperatura"),
            "humedad_relativa":        buscar_valor_fila(ws, "Humedad"),
            "metodo_utilizado":        buscar_valor_fila(ws, "Método utilizado"),
            "lugar_calibracion":       buscar_valor_fila(ws, "Lugar de la calibración"),
            "calibrado_por":           buscar_valor_fila(ws, "Calibró"),
            "aprobado_por":            buscar_valor_fila(ws, "Aprobó"),
            "fecha_recepcion":         fecha_recepcion,
            "fecha_calibracion":       fecha_calibracion,
            "fecha_emision":           fecha_emision,
        }, None

    except Exception as e:
        return None, str(e)


# ============================================================
# EXTRACCIÓN DESDE PDF
# ============================================================
def extraer_pdf(ruta_archivo: str) -> tuple:
    """Extrae datos del PDF del certificado."""
    if not TIENE_PDF:
        return None, "pdfplumber no instalado"
    try:
        with pdfplumber.open(ruta_archivo) as pdf:
            texto = "\n".join(p.extract_text() or '' for p in pdf.pages[:2])

        def buscar_patron(patrones):
            for patron in patrones:
                m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
                if m:
                    return m.group(1).strip() if m.lastindex else m.group().strip()
            return None

        def buscar_linea_siguiente(etiqueta):
            """Busca la línea siguiente a una etiqueta."""
            lines = texto.split('\n')
            for i, line in enumerate(lines):
                if etiqueta.lower() in line.lower():
                    # Buscar en la misma línea después de ':' o en la siguiente
                    partes = re.split(r':\s*', line, maxsplit=1)
                    if len(partes) > 1 and partes[1].strip():
                        return partes[1].strip()
                    if i + 1 < len(lines) and lines[i + 1].strip():
                        return lines[i + 1].strip()
            return None

        # Número de informe (ej: No. LMD-143-25)
        numero = buscar_patron([
            r'No\.\s+(LM[A-Z]-\d+-\d+)',
            r'No\.\s+([A-Z]{2,5}-\d+-\d+)',
            r'Informe[:\s]+([A-Z0-9\-]+)',
        ])

        fecha_emision     = limpiar_fecha(buscar_linea_siguiente("Fecha de emisión"))
        fecha_recepcion   = limpiar_fecha(buscar_linea_siguiente("Fecha de recepción"))
        fecha_calibracion = limpiar_fecha(buscar_linea_siguiente("Fecha de calibración"))

        return {
            "numero_informe":          numero,
            "nombre_cliente":          buscar_linea_siguiente("Nombre del cliente"),
            "direccion":               buscar_linea_siguiente("Dirección"),
            "atencion_a":              buscar_linea_siguiente("Atención a"),
            "descripcion_instrumento": buscar_linea_siguiente("Descripción del instrumento"),
            "alcance":                 buscar_linea_siguiente("Alcance"),
            "numero_serie":            buscar_patron([r'No\.\s*[Dd]e\s*[Ss]erie[:\s]+(\S+)']),
            "identificacion":          buscar_linea_siguiente("Identificación"),
            "modelo":                  buscar_linea_siguiente("Modelo"),
            "marca":                   buscar_linea_siguiente("Marca"),
            "magnitud_evaluada":       buscar_linea_siguiente("Magnitud evaluada"),
            "resultado_calibracion":   buscar_linea_siguiente("Resultado de calibración"),
            "incertidumbre":           buscar_linea_siguiente("Incertidumbre"),
            "temperatura":             buscar_patron([r'Temperatura[:\s]+([\d\s°C±]+)']),
            "humedad_relativa":        buscar_patron([r'Humedad[:\s]+([\d\s%±]+)']),
            "metodo_utilizado":        buscar_linea_siguiente("Método utilizado"),
            "lugar_calibracion":       buscar_linea_siguiente("Lugar de la calibración"),
            "calibrado_por":           buscar_linea_siguiente("Calibró"),
            "aprobado_por":            buscar_linea_siguiente("Aprobó"),
            "fecha_recepcion":         fecha_recepcion,
            "fecha_calibracion":       fecha_calibracion,
            "fecha_emision":           fecha_emision,
        }, None

    except Exception as e:
        return None, str(e)


# ============================================================
# VERIFICAR SI EL ARCHIVO ES UN CERTIFICADO SIDEC
# ============================================================
def es_certificado(datos: dict) -> bool:
    """
    Verifica si el archivo extraído parece ser un certificado de calibración.
    Un certificado válido debe tener al menos 2 de estos campos.
    """
    campos_clave = [
        'numero_informe', 'nombre_cliente',
        'descripcion_instrumento', 'fecha_emision', 'magnitud_evaluada'
    ]
    llenos = sum(1 for c in campos_clave if datos.get(c))
    return llenos >= 2


# ============================================================
# ESCANEO DE ARCHIVOS
# ============================================================
def escanear_carpeta(carpeta_raiz: str, anio_filtro: int = None) -> list:
    """
    Recorre la carpeta raíz y devuelve lista de archivos a procesar.
    Cada elemento: {'ruta', 'tipo', 'empleado', 'anio', 'mes', 'mes_nombre'}
    """
    archivos = []
    raiz = Path(carpeta_raiz)

    if not raiz.exists():
        log.error(f"Carpeta no encontrada: {carpeta_raiz}")
        return []

    for ruta in raiz.rglob('*'):
        if not ruta.is_file():
            continue
        if ruta.name.startswith('~$'):  # archivos temporales de Office
            continue

        tipo = identificar_tipo_archivo(str(ruta))
        if tipo in ('skip', 'desconocido'):
            continue

        ctx = extraer_contexto_ruta(str(ruta), carpeta_raiz)

        # Filtro por año si se especificó
        if anio_filtro and ctx.get('anio') != anio_filtro:
            continue

        archivos.append({
            'ruta':        str(ruta),
            'tipo':        tipo,
            'empleado':    ctx.get('empleado'),
            'anio_ruta':   ctx.get('anio'),
            'mes':         ctx.get('mes'),
            'mes_nombre':  ctx.get('mes_nombre'),
        })

    return archivos


# ============================================================
# IMPORTACIÓN PRINCIPAL
# ============================================================
def importar(archivos: list, conn, empleado_override: str = None) -> dict:
    cursor = conn.cursor()
    stats = {
        'total': len(archivos), 'exitosos': 0,
        'fallidos': 0, 'no_certificados': 0,
        'errores': []
    }
    lote = []

    COLUMNAS = [
        'numero_informe', 'anio_emision', 'nombre_cliente', 'direccion',
        'atencion_a', 'descripcion_instrumento', 'alcance', 'numero_serie',
        'identificacion', 'modelo', 'marca', 'magnitud_evaluada',
        'resultado_calibracion', 'incertidumbre', 'temperatura', 'humedad_relativa',
        'fecha_recepcion', 'fecha_calibracion', 'fecha_emision',
        'metodo_utilizado', 'lugar_calibracion', 'calibrado_por', 'aprobado_por',
        'ruta_archivo_origen', 'importado_por', 'fecha_importacion'
    ]

    def flush_lote():
        if not lote: return
        try:
            valores = [tuple(d.get(c) for c in COLUMNAS) for d in lote]
            execute_values(cursor,
                f"INSERT INTO certificados ({', '.join(COLUMNAS)}) VALUES %s ON CONFLICT DO NOTHING",
                valores
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error(f"Error insertando lote: {e}")
        lote.clear()

    iter_archivos = tqdm(archivos, desc="Importando", unit="archivo") if TIENE_TQDM else archivos

    for archivo in iter_archivos:
        ruta   = archivo['ruta']
        tipo   = archivo['tipo']
        nombre = Path(ruta).name

        # Extraer datos según tipo
        if tipo == 'excel':
            datos, error = extraer_excel(ruta)
        elif tipo == 'pdf':
            datos, error = extraer_pdf(ruta)
        else:
            continue

        if error or not datos:
            stats['fallidos'] += 1
            stats['errores'].append({'archivo': ruta, 'error': error or 'Sin datos'})
            log.warning(f"{WARN} {nombre}: {error}")
            continue

        # Verificar que sea un certificado real
        if not es_certificado(datos):
            stats['no_certificados'] += 1
            log.info(f"{INFO} {nombre}: no parece ser un certificado (datos insuficientes)")
            continue

        # Determinar año de emisión
        anio = None
        if datos.get('fecha_emision'):
            anio = datos['fecha_emision'].year
        elif archivo.get('anio_ruta'):
            anio = archivo['anio_ruta']
        else:
            anio = datetime.now().year

        # Código del empleado
        empleado = empleado_override or archivo.get('empleado') or 'sin_asignar'

        datos['anio_emision']       = anio
        datos['ruta_archivo_origen'] = ruta
        datos['importado_por']      = empleado
        datos['fecha_importacion']  = datetime.now()

        lote.append(datos)
        stats['exitosos'] += 1
        log.info(f"{OK} {nombre} → empleado:{empleado} año:{anio}")

        if len(lote) >= CHUNK_SIZE:
            flush_lote()
            log.info(f"   Lote insertado ({stats['exitosos']} exitosos hasta ahora)")

    flush_lote()
    cursor.close()
    return stats


# ============================================================
# MODO ESCANEO (solo ver qué hay sin importar)
# ============================================================
def modo_escanear(archivos: list):
    print(f"\n{'='*65}")
    print(f"  ESCANEO — {len(archivos)} archivos encontrados")
    print(f"{'='*65}")

    por_empleado = {}
    por_anio     = {}
    por_tipo     = {}

    for a in archivos:
        e = a.get('empleado') or '(sin empleado)'
        y = a.get('anio_ruta') or '(sin año)'
        t = a.get('tipo', '?')
        por_empleado.setdefault(e, 0); por_empleado[e] += 1
        por_anio.setdefault(y, 0);     por_anio[y]     += 1
        por_tipo.setdefault(t, 0);     por_tipo[t]     += 1

    print(f"\n  Por empleado:")
    for k, v in sorted(por_empleado.items()):
        print(f"    {k:<30} {v:>5} archivos")

    print(f"\n  Por año:")
    for k, v in sorted(por_anio.items()):
        print(f"    {str(k):<10} {v:>5} archivos")

    print(f"\n  Por tipo:")
    for k, v in sorted(por_tipo.items()):
        print(f"    {k:<10} {v:>5} archivos")
    print()


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='SIDEC — Importación masiva por empleado/año/mes'
    )
    parser.add_argument('--carpeta',       type=str, help='Carpeta raíz (default: config CARPETA_RAIZ)')
    parser.add_argument('--empleado',      type=str, help='Código del empleado (sobreescribe detección automática)')
    parser.add_argument('--anio',          type=int, help='Solo importar este año')
    parser.add_argument('--solo-escanear', action='store_true', help='Solo escanear sin importar')
    args = parser.parse_args()

    carpeta = args.carpeta or CARPETA_RAIZ

    print(f"\n{'='*65}")
    print(f"  {OK} SIDEC — Importación masiva de certificados{RST}")
    print(f"  Carpeta:  {carpeta}")
    print(f"  Empleado: {args.empleado or '(detección automática)'}")
    print(f"  Año:      {args.anio or 'todos'}")
    print(f"{'='*65}\n")

    # Escanear archivos
    log.info("Escaneando archivos...")
    archivos = escanear_carpeta(carpeta, anio_filtro=args.anio)
    log.info(f"Total encontrados: {len(archivos)}")

    if not archivos:
        print(f"\n{WARN} No se encontraron archivos en: {carpeta}")
        sys.exit(0)

    # Solo escanear
    if args.solo_escanear:
        modo_escanear(archivos)
        sys.exit(0)

    # Conectar a la base de datos
    if not TIENE_DB:
        log.error(f"{ERR} psycopg2 no disponible. El script debe ejecutarse desde el venv:")
        log.error("     venv\Scripts\python.exe scripts/importar_masivo.py")
        sys.exit(1)
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        log.info(f"{OK} Conectado a PostgreSQL — {DB_CONFIG['dbname']}")
    except Exception as e:
        log.error(f"{ERR} No se pudo conectar a la BD: {e}")
        sys.exit(1)

    # Importar
    inicio = datetime.now()
    stats  = importar(archivos, conn, empleado_override=args.empleado)
    conn.close()
    duracion = datetime.now() - inicio

    # Guardar log de errores si hay
    if stats['errores']:
        err_file = f'errores_{ts}.json'
        with open(err_file, 'w', encoding='utf-8') as f:
            json.dump(stats['errores'], f, ensure_ascii=False, indent=2, default=str)
        print(f"\n{WARN} Errores guardados en: {err_file}")

    print(f"\n{'='*65}")
    print(f"  RESUMEN FINAL")
    print(f"{'='*65}")
    print(f"  Total archivos encontrados : {stats['total']}")
    print(f"  {OK} Importados exitosamente  : {stats['exitosos']}")
    print(f"  {WARN} No son certificados     : {stats['no_certificados']}")
    print(f"  {ERR} Fallidos                : {stats['fallidos']}")
    print(f"  ⏱  Tiempo total             : {duracion}")
    print(f"{'='*65}\n")
