"""
scripts/importar_masivo.py
SIDEC — Importación de certificados
=====================================
Llamado desde routes/admin.js para procesar archivos Excel/PDF.
Extrae SOLO los datos de la PORTADA y los guarda en PostgreSQL.

Formato de salida JSON (para Node.js):
    __JSON_START__
    {"total": 10, "exitosos": 8, ...}
    __JSON_END__
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

# ── Librerías requeridas ───────────────────────────────────
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print(json.dumps({"error": "psycopg2 no instalado"}), file=sys.stderr)
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    print(json.dumps({"error": "openpyxl no instalado"}), file=sys.stderr)
    sys.exit(1)

# PDF es opcional
try:
    import pdfplumber
    TIENE_PDF = True
except ImportError:
    TIENE_PDF = False

# ── Configuración de BD ────────────────────────────────────
DB_CONFIG = {
    'host':     os.getenv('DB_HOST',     'localhost'),
    'port':     int(os.getenv('DB_PORT', 5432)),
    'dbname':   os.getenv('DB_NAME',     'sidec_db'),
    'user':     os.getenv('DB_USER',     'postgres'),
    'password': os.getenv('DB_PASSWORD', 'sidecmexico'),
}


# ============================================================
# FUNCIONES DE EXTRACCIÓN
# ============================================================

def buscar_valor_en_fila(hoja, texto_clave):
    """Busca texto_clave y devuelve el valor de la celda contigua."""
    for fila in hoja.iter_rows():
        celda_clave = None
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    if texto_clave.lower() in celda.value.lower():
                        celda_clave = celda
                        break
            except:
                continue
        
        if celda_clave:
            for celda_misma_fila in fila:
                try:
                    if celda_misma_fila != celda_clave and celda_misma_fila.value:
                        valor = str(celda_misma_fila.value).strip()
                        if valor and len(valor) > 1:
                            return valor
                except:
                    continue
    return None


def buscar_valor_relativo(hoja, texto_clave, df=0, dc=1):
    """Busca texto_clave y devuelve valor en posición relativa."""
    for fila in hoja.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    if texto_clave.lower() in celda.value.lower():
                        valor = hoja.cell(row=celda.row + df, column=celda.column + dc).value
                        if valor:
                            return str(valor).strip()
            except:
                continue
    return None


def obtener_hoja_portada(wb):
    """Busca la hoja PORTADA o usa la primera hoja."""
    for nombre in wb.sheetnames:
        if 'portada' in nombre.lower():
            return wb[nombre]
    return wb.active


def limpiar_fecha(valor):
    """Parsea fechas en múltiples formatos."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    
    formatos = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%Y%m%d']
    valor_str = str(valor).strip()
    if ' ' in valor_str:
        valor_str = valor_str.split(' ')[0]
    
    for fmt in formatos:
        try:
            return datetime.strptime(valor_str, fmt).date()
        except:
            continue
    return None


def extraer_numero_informe(ws):
    """Extrae el número de informe de la portada."""
    # Método 1: Buscar después de "Hoja 1 de X"
    for fila in ws.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    if 'hoja 1 de' in celda.value.lower():
                        # Buscar en celdas cercanas
                        for r in range(celda.row - 1, celda.row + 3):
                            for c in range(celda.column - 2, celda.column + 3):
                                try:
                                    val = ws.cell(row=r, column=c).value
                                    if val and isinstance(val, str):
                                        match = re.search(r'([A-Z]{2,5}-\d+-\d+)', val)
                                        if match:
                                            return match.group(1)
                                except:
                                    continue
            except:
                continue
    
    # Método 2: Buscar en todo el libro
    for fila in ws.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    match = re.search(r'(?:No\.?\s*)?([A-Z]{2,5}-\d+-\d+)', celda.value)
                    if match:
                        return match.group(1)
            except:
                continue
    return None


def extraer_datos_excel(ruta_archivo):
    """Extrae campos del certificado desde Excel."""
    try:
        wb = openpyxl.load_workbook(ruta_archivo, data_only=True)
        ws = obtener_hoja_portada(wb)
        
        if not ws:
            return None, "Hoja PORTADA no encontrada"
        
        # Fechas (probar ambos formatos)
        fecha_emision     = limpiar_fecha(buscar_valor_en_fila(ws, "Fecha de emisión"))
        fecha_recepcion   = limpiar_fecha(buscar_valor_en_fila(ws, "Fecha de recepción"))
        fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, "Fecha de calibración"))
        if not fecha_calibracion:
            fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, "Fecha del estudio"))
        
        # Número de informe
        numero_informe = extraer_numero_informe(ws)
        
        # Año
        anio = None
        if fecha_emision:
            anio = fecha_emision.year
        elif numero_informe:
            match = re.search(r'-(\d{2})$', numero_informe)
            if match:
                sufijo = int(match.group(1))
                anio = 2000 + sufijo if sufijo <= 50 else 1900 + sufijo
        if not anio:
            match = re.search(r'20[1-3]\d', ruta_archivo)
            if match:
                anio = int(match.group())
        if not anio:
            anio = datetime.now().year
        
        # Campos principales
        datos = {
            "numero_informe":          numero_informe,
            "anio_emision":            anio,
            "nombre_cliente":          buscar_valor_en_fila(ws, "Nombre del cliente"),
            "descripcion_instrumento": buscar_valor_en_fila(ws, "Descripción del instrumento"),
            "alcance":                 buscar_valor_en_fila(ws, "Alcance"),
            "numero_serie":            buscar_valor_relativo(ws, "No. De Serie", 0, 2) or 
                                      buscar_valor_relativo(ws, "No. de serie", 0, 2),
            "identificacion":          buscar_valor_en_fila(ws, "Identificación"),
            "modelo":                  buscar_valor_en_fila(ws, "Modelo"),
            "marca":                   buscar_valor_en_fila(ws, "Marca"),
            "magnitud_evaluada":       buscar_valor_en_fila(ws, "Magnitud evaluada"),
            "resultado_calibracion":   buscar_valor_en_fila(ws, "Resultado de calibración") or 
                                      buscar_valor_en_fila(ws, "Resultado del estudio"),
            "lugar_calibracion":       buscar_valor_en_fila(ws, "Lugar de la calibración") or 
                                      buscar_valor_en_fila(ws, "Lugar del estudio"),
            "calibrado_por":           buscar_valor_en_fila(ws, "Calibró") or 
                                      buscar_valor_en_fila(ws, "Realizó"),
            "aprobado_por":            buscar_valor_en_fila(ws, "Aprobó"),
            "fecha_recepcion":         fecha_recepcion,
            "fecha_calibracion":       fecha_calibracion,
            "fecha_emision":           fecha_emision,
            "ruta_archivo_origen":     ruta_archivo,
            "fecha_importacion":       datetime.now(),
        }
        
        # Validar datos mínimos
        if not datos.get("nombre_cliente") and not datos.get("descripcion_instrumento"):
            return None, "No se encontraron datos de certificado"
        
        return datos, None
    
    except Exception as e:
        return None, f"Error: {str(e)}"


# ============================================================
# ESCANEO
# ============================================================

def escanear_carpeta(carpeta, anio_filtro=None):
    """Escanea carpeta y devuelve lista de archivos."""
    archivos = []
    raiz = Path(carpeta)
    
    if not raiz.exists():
        return []
    
    for ruta in raiz.rglob('*'):
        if not ruta.is_file():
            continue
        if ruta.name.startswith('~$'):
            continue
        
        ext = ruta.suffix.lower()
        if ext not in ('.xlsx', '.xls', '.pdf'):
            continue
        
        if anio_filtro:
            match = re.search(r'20[1-3]\d', str(ruta))
            if match and int(match.group()) != int(anio_filtro):
                continue
        
        archivos.append(str(ruta))
    
    return sorted(archivos)


# ============================================================
# IMPORTACIÓN
# ============================================================

def insertar_certificados(conn, datos_lista, empleado=None):
    """Inserta certificados en PostgreSQL."""
    cursor = conn.cursor()
    
    columnas = [
        'numero_informe', 'anio_emision', 'nombre_cliente',
        'descripcion_instrumento', 'alcance', 'numero_serie',
        'identificacion', 'modelo', 'marca', 'magnitud_evaluada',
        'resultado_calibracion', 'lugar_calibracion',
        'calibrado_por', 'aprobado_por',
        'fecha_recepcion', 'fecha_calibracion', 'fecha_emision',
        'ruta_archivo_origen', 'fecha_importacion', 'importado_por'
    ]
    
    exitosos = 0
    for datos in datos_lista:
        try:
            if empleado:
                datos['importado_por'] = empleado
            
            valores = [datos.get(c) for c in columnas]
            placeholders = ','.join(['%s'] * len(columnas))
            
            cursor.execute(f"""
                INSERT INTO certificados ({', '.join(columnas)})
                VALUES ({placeholders})
                ON CONFLICT DO NOTHING
            """, valores)
            exitosos += 1
        except Exception as e:
            print(f"Error insertando: {e}", file=sys.stderr)
    
    conn.commit()
    cursor.close()
    return exitosos


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SIDEC - Importar certificados')
    parser.add_argument('--json-output', action='store_true', help='Salida JSON para Node.js')
    parser.add_argument('--carpeta', type=str, required=True, help='Carpeta a procesar')
    parser.add_argument('--empleado', type=str, default=None, help='Código de empleado')
    parser.add_argument('--anio', type=int, default=None, help='Filtrar por año')
    parser.add_argument('--solo-escanear', action='store_true', help='Solo escanear')
    args = parser.parse_args()
    
    inicio = datetime.now()
    
    # Escanear archivos
    archivos = escanear_carpeta(args.carpeta, args.anio)
    
    # Solo escanear
    if args.solo_escanear:
        # Clasificar por tipo y año
        por_tipo = {'excel': 0, 'pdf': 0}
        por_anio = {}
        for archivo in archivos:
            ext = Path(archivo).suffix.lower()
            if ext in ('.xlsx', '.xls'):
                por_tipo['excel'] += 1
            elif ext == '.pdf':
                por_tipo['pdf'] += 1
            
            match = re.search(r'20[1-3]\d', archivo)
            if match:
                anio_str = match.group()
                por_anio[anio_str] = por_anio.get(anio_str, 0) + 1
        
        resultado = {
            "total": len(archivos),
            "exitosos": 0,
            "fallidos": 0,
            "no_certificados": 0,
            "duracion": str(datetime.now() - inicio),
            "por_tipo": por_tipo,
            "por_anio": por_anio,
            "por_empleado": {},
            "errores": []
        }
        
        if args.json_output:
            print('__JSON_START__')
            print(json.dumps(resultado, default=str))
            print('__JSON_END__')
        else:
            print(json.dumps(resultado, default=str))
        sys.exit(0)
    
    # Importar
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        resultado = {"error": f"No se pudo conectar a PostgreSQL: {e}"}
        print(json.dumps(resultado))
        sys.exit(1)
    
    datos_certificados = []
    errores = []
    no_certs = 0
    
    for archivo in archivos:
        datos, error = extraer_datos_excel(archivo)
        
        if error:
            errores.append({"archivo": archivo, "error": error})
        elif datos:
            datos_certificados.append(datos)
        else:
            no_certs += 1
    
    # Insertar en BD
    exitosos = insertar_certificados(conn, datos_certificados, args.empleado)
    conn.close()
    
    resultado = {
        "total": len(archivos),
        "exitosos": exitosos,
        "fallidos": len(errores),
        "no_certificados": no_certs,
        "duracion": str(datetime.now() - inicio),
        "errores": errores[:50]
    }
    
    if args.json_output:
        print('__JSON_START__')
        print(json.dumps(resultado, default=str))
        print('__JSON_END__')
    else:
        print(json.dumps(resultado, default=str))