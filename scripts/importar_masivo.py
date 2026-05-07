"""
scripts/importar_masivo.py
SIDEC — Importación masiva de certificados (solo Excel)
Soporte bilingüe español/inglés.
PDFs comentados para activación futura.
"""

import os, sys, re, json, argparse
from datetime import datetime
from pathlib import Path

# ── Librerías ──────────────────────────────────────────
try:
    import psycopg2
except ImportError:
    print(json.dumps({"error": "psycopg2 no instalado"}), file=sys.stderr)
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    print(json.dumps({"error": "openpyxl no instalado"}), file=sys.stderr)
    sys.exit(1)

import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

try:
    import xlrd
    TIENE_XLRD = True
except ImportError:
    TIENE_XLRD = False

# PDFs (comentados por ahora)
# try:
#     import pdfplumber
#     TIENE_PDFPLUMBER = True
# except ImportError:
#     TIENE_PDFPLUMBER = False
#
# try:
#     import fitz  # pymupdf
#     TIENE_PYMUPDF = True
# except ImportError:
#     TIENE_PYMUPDF = False
#
# try:
#     import pytesseract
#     from PIL import Image
#     TIENE_OCR = True
# except ImportError:
#     TIENE_OCR = False

# Extractor SIDEC para PDFs (módulo local, comentado)
# sys.path.insert(0, str(Path(__file__).parent))
# try:
#     from extraer_pdf_sidec import extraer_certificado_sidec
# except ImportError:
#     extraer_certificado_sidec = None

# ── Configuración BD ────────────────────────────────────
DB_CONFIG = {
    'host':     os.getenv('DB_HOST',     'localhost'),
    'port':     int(os.getenv('DB_PORT', 5432)),
    'dbname':   os.getenv('DB_NAME',     'sidec_db'),
    'user':     os.getenv('DB_USER',     'postgres'),
    'password': os.getenv('DB_PASSWORD', 'sidecmexico'),
}

# ── Funciones Excel (openpyxl) ──────────────────────────
def buscar_valor_en_fila(hoja, etiquetas):
    for fila in hoja.iter_rows():
        clave = None
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    for eti in etiquetas:
                        if eti.lower() in celda.value.lower():
                            clave = celda
                            break
                    if clave: break
            except: continue
        if clave:
            for celda in fila:
                try:
                    if celda != clave and celda.value:
                        val = str(celda.value).strip()
                        if val and len(val) > 1:
                            return val
                except: continue
    return None

def buscar_valor_multilenguaje(hoja, etiquetas_es, etiquetas_en=None):
    val = buscar_valor_en_fila(hoja, etiquetas_es)
    if val: return val, None
    if etiquetas_en:
        val = buscar_valor_en_fila(hoja, etiquetas_en)
        if val: return val, None
    faltantes = ', '.join(etiquetas_es + (etiquetas_en or []))
    return None, f"No se encontró: {faltantes}"

def buscar_valor_relativo(hoja, texto_clave, df=0, dc=1):
    for fila in hoja.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str) and texto_clave.lower() in celda.value.lower():
                    val = hoja.cell(row=celda.row+df, column=celda.column+dc).value
                    if val: return str(val).strip()
            except: continue
    return None

def obtener_hoja_portada(wb):
    for nombre in wb.sheetnames:
        nl = nombre.lower()
        if 'portada' in nl or 'informe de calibración' in nl:
            return wb[nombre]
    return wb.active

def limpiar_fecha(valor):
    if not valor: return None
    if isinstance(valor, datetime): return valor.date()
    formatos = [
        '%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%m/%d/%Y','%Y%m%d',
        '%d-%b-%y','%d-%b-%Y','%d-%B-%y','%d-%B-%Y',
        '%Y/%m/%d','%d.%m.%Y'
    ]
    valor_str = str(valor).strip()
    if ' ' in valor_str: valor_str = valor_str.split(' ')[0]
    for fmt in formatos:
        try: return datetime.strptime(valor_str, fmt).date()
        except: continue
    return None

def extraer_numero_informe(ws):
    for fila in ws.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str) and 'hoja 1 de' in celda.value.lower():
                    for r in range(celda.row-1, celda.row+3):
                        for c in range(celda.column-2, celda.column+3):
                            try:
                                v = ws.cell(row=r, column=c).value
                                if v and isinstance(v, str):
                                    m = re.search(r'([A-Z]{2,5}-\d+-\d+)', v)
                                    if m: return m.group(1)
                            except: continue
            except: continue
    for fila in ws.iter_rows():
        for celda in fila:
            try:
                if celda.value and isinstance(celda.value, str):
                    m = re.search(r'(?:No\.?\s*)?([A-Z]{2,5}-\d+-\d+)', celda.value)
                    if m: return m.group(1)
            except: continue
    return None

def extraer_datos_excel(ruta_archivo):
    ext = Path(ruta_archivo).suffix.lower()
    if ext == '.xls' and not ruta_archivo.lower().endswith('.xlsx'):
        return extraer_datos_xls(ruta_archivo)
    try:
        wb = openpyxl.load_workbook(ruta_archivo, data_only=True)
        ws = obtener_hoja_portada(wb)
        if not ws:
            return None, "Hoja PORTADA o 'Informe de Calibración' no encontrada"

        fecha_emision     = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de emisión","Date of issue"]))
        fecha_recepcion   = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de recepción","Reception date"]))
        fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de calibración","Date of calibration"]))
        if not fecha_calibracion:
            fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha del estudio","Study date"]))

        numero_informe = extraer_numero_informe(ws)

        nombre_cliente, err1 = buscar_valor_multilenguaje(ws,
            ["Nombre del cliente"], ["Customer name","Client name"])
        descripcion, err2 = buscar_valor_multilenguaje(ws,
            ["Descripción del instrumento"], ["Instrument description","Description"])
        if not nombre_cliente and not descripcion:
            return None, f"Falta cliente e instrumento: {err1}, {err2}"

        numero_serie, _ = buscar_valor_multilenguaje(ws,
            ["No. De Serie","No. de serie"], ["Serial number","Serial No"])
        identificacion, _ = buscar_valor_multilenguaje(ws,
            ["Identificación No","Identificacion No"], ["Identification","ID"])
        modelo, _ = buscar_valor_multilenguaje(ws, ["Modelo"], ["Model"])
        marca, _ = buscar_valor_multilenguaje(ws, ["Marca"], ["Manufacturer","Brand"])
        magnitud, _ = buscar_valor_multilenguaje(ws,
            ["Magnitud evaluada"], ["Evaluated quality","Magnitude"])
        resultado, _ = buscar_valor_multilenguaje(ws,
            ["Resultado de calibración","Resultado del estudio"],
            ["Calibration result","Study result"])
        lugar, _ = buscar_valor_multilenguaje(ws,
            ["Lugar de la calibración","Lugar del estudio"],
            ["Place of calibration","Study place"])
        calibro, _ = buscar_valor_multilenguaje(ws,
            ["Calibró","Realizó"], ["Calibrated by","Done by"])
        aprobo, _ = buscar_valor_multilenguaje(ws, ["Aprobó"], ["Approved by"])

        anio = None
        if fecha_emision: anio = fecha_emision.year
        elif numero_informe:
            m = re.search(r'-(\d{2})$', numero_informe)
            if m: anio = 2000+int(m.group(1)) if int(m.group(1))<=50 else 1900+int(m.group(1))
        if not anio:
            m = re.search(r'20[1-3]\d', ruta_archivo)
            if m: anio = int(m.group())
        if not anio: anio = datetime.now().year

        datos = {
            "numero_informe": numero_informe,
            "anio_emision": anio,
            "nombre_cliente": nombre_cliente,
            "descripcion_instrumento": descripcion,
            "alcance": buscar_valor_en_fila(ws, ["Alcance de Medición","Alcance","Range"]),
            "numero_serie": numero_serie,
            "identificacion": identificacion,
            "modelo": modelo,
            "marca": marca,
            "magnitud_evaluada": magnitud,
            "resultado_calibracion": resultado,
            "lugar_calibracion": lugar,
            "calibrado_por": calibro,
            "aprobado_por": aprobo,
            "fecha_recepcion": fecha_recepcion,
            "fecha_calibracion": fecha_calibracion,
            "fecha_emision": fecha_emision,
            "ruta_archivo_origen": ruta_archivo,
            "fecha_importacion": datetime.now(),
        }
        return datos, None
    except Exception as e:
        return None, f"Error Excel: {str(e)}"

# ── Extracción .xls antiguo ─────────────────────────────
def extraer_datos_xls(ruta_archivo):
    if not TIENE_XLRD:
        return None, "xlrd no instalado. pip install xlrd==1.2.0"
    try:
        wb = xlrd.open_workbook(ruta_archivo)
        ws = None
        for n in wb.sheet_names():
            if 'portada' in n.lower() or 'informe de calibración' in n.lower():
                ws = wb.sheet_by_name(n); break
        if not ws: ws = wb.sheet_by_index(0)

        class FakeCell:
            def __init__(self, value): self.value = value

        filas = []
        for r in range(ws.nrows):
            fila = []
            for c in range(ws.ncols):
                v = ws.cell_value(r,c)
                if isinstance(v, float) and v==int(v): v = str(int(v))
                elif isinstance(v, float): v = str(v)
                else: v = str(v) if v else None
                fila.append(FakeCell(v))
            filas.append(fila)

        def buscar_fila(etiquetas):
            for fila in filas:
                clave = None
                for celda in fila:
                    try:
                        if celda.value:
                            for e in etiquetas:
                                if e.lower() in celda.value.lower():
                                    clave=celda; break
                            if clave: break
                    except: continue
                if clave:
                    for celda in fila:
                        try:
                            if celda!=clave and celda.value:
                                val = str(celda.value).strip()
                                if val and len(val)>1: return val
                        except: continue
            return None

        def multileng_xls(es, en=None):
            v = buscar_fila(es)
            if v: return v, None
            if en:
                v = buscar_fila(en)
                if v: return v, None
            return None, f"No se encontró: {', '.join(es+(en or []))}"

        nombre_cliente, err1 = multileng_xls(["Nombre del cliente"],["Customer name","Client name"])
        descripcion, err2 = multileng_xls(["Descripción del instrumento"],["Instrument description"])
        if not nombre_cliente and not descripcion:
            return None, f"Falta cliente e instrumento: {err1}, {err2}"

        fecha_em = limpiar_fecha(buscar_fila(["Fecha de emisión","Date of issue"]))
        fecha_rec = limpiar_fecha(buscar_fila(["Fecha de recepción","Reception date"]))
        fecha_cal = limpiar_fecha(buscar_fila(["Fecha de calibración","Date of calibration"]))
        if not fecha_cal: fecha_cal = limpiar_fecha(buscar_fila(["Fecha del estudio","Study date"]))

        num_info = None
        for fila in filas:
            for celda in fila:
                try:
                    m = re.search(r'([A-Z]{2,5}-\d+-\d+)', str(celda.value) if celda.value else '')
                    if m: num_info=m.group(1); break
                except: continue
            if num_info: break

        anio = None
        if fecha_em: anio=fecha_em.year
        elif num_info:
            m = re.search(r'-(\d{2})$', num_info)
            if m: anio = 2000+int(m.group(1)) if int(m.group(1))<=50 else 1900+int(m.group(1))
        if not anio:
            m = re.search(r'20[1-3]\d', ruta_archivo); 
            if m: anio=int(m.group())
        if not anio: anio=datetime.now().year

        datos = {
            "numero_informe": num_info,
            "anio_emision": anio,
            "nombre_cliente": nombre_cliente,
            "descripcion_instrumento": descripcion,
            "alcance": buscar_fila(["Alcance de Medición","Alcance","Range"]),
            "numero_serie": multileng_xls(["No. De Serie","No. de serie"],["Serial number"])[0],
            "identificacion": multileng_xls(["Identificación No","Identificacion No"],["Identification"])[0],
            "modelo": buscar_fila(["Modelo"]),
            "marca": buscar_fila(["Marca","Manufacturer"]),
            "magnitud_evaluada": buscar_fila(["Magnitud evaluada","Evaluated quality"]),
            "resultado_calibracion": buscar_fila(["Resultado de calibración","Calibration result"]),
            "lugar_calibracion": buscar_fila(["Lugar de la calibración","Place of calibration"]),
            "calibrado_por": buscar_fila(["Calibró","Calibrated by"]),
            "aprobado_por": buscar_fila(["Aprobó","Approved by"]),
            "fecha_recepcion": fecha_rec,
            "fecha_calibracion": fecha_cal,
            "fecha_emision": fecha_em,
            "ruta_archivo_origen": ruta_archivo,
            "fecha_importacion": datetime.now(),
        }
        return datos, None
    except Exception as e:
        return None, f"Error XLS: {str(e)}"

# ── Extracción de PDFs (comentada) ──────────────────────
# def extraer_texto_pdf(ruta_archivo): ...

# def extraer_datos_pdf(ruta_archivo): ...

# ── Escaneo e inserción ─────────────────────────────────
def escanear_carpeta(carpeta, anio_filtro=None):
    archivos = []
    raiz = Path(carpeta)
    if not raiz.exists(): return []
    for ruta in raiz.rglob('*'):
        if not ruta.is_file() or ruta.name.startswith('~$'): continue
        ext = ruta.suffix.lower()
        if ext not in ('.xlsx','.xls'): continue   # solo Excel
        if anio_filtro:
            m = re.search(r'20[1-3]\d', str(ruta))
            if m and int(m.group())!=int(anio_filtro): continue
        archivos.append(str(ruta))
    return sorted(archivos)

def insertar_certificados(conn, datos_lista, empleado=None):
    cursor = conn.cursor()
    columnas = [
        'numero_informe','anio_emision','nombre_cliente',
        'descripcion_instrumento','alcance','numero_serie',
        'identificacion','modelo','marca','magnitud_evaluada',
        'resultado_calibracion','lugar_calibracion',
        'calibrado_por','aprobado_por',
        'fecha_recepcion','fecha_calibracion','fecha_emision',
        'ruta_archivo_origen','fecha_importacion','importado_por'
    ]
    exitosos = 0
    omitidos = 0
    for datos in datos_lista:
        try:
            if empleado: datos['importado_por'] = empleado
            vals = [datos.get(c) for c in columnas]
            ph = ','.join(['%s']*len(columnas))
            cursor.execute(f"""
                INSERT INTO certificados ({', '.join(columnas)})
                VALUES ({ph})
                ON CONFLICT (numero_informe) DO NOTHING
            """, vals)
            if cursor.rowcount > 0:
                exitosos += 1
            else:
                omitidos += 1
        except Exception as e:
            print(f"Error insertando: {e}", file=sys.stderr)
    conn.commit()
    cursor.close()
    return exitosos, omitidos

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json-output', action='store_true')
    parser.add_argument('--carpeta', required=True)
    parser.add_argument('--empleado', default=None)
    parser.add_argument('--anio', type=int, default=None)
    parser.add_argument('--solo-escanear', action='store_true')
    args = parser.parse_args()

    archivos = escanear_carpeta(args.carpeta, args.anio)

    if args.solo_escanear:
        por_tipo = {'excel':0}
        for a in archivos:
            ext = Path(a).suffix.lower()
            if ext in ('.xlsx','.xls'): por_tipo['excel']+=1
        res = {"total":len(archivos),"por_tipo":por_tipo,"archivos":[Path(a).name for a in archivos[:20]]}
        if args.json_output:
            print('__JSON_START__'); print(json.dumps(res,default=str)); print('__JSON_END__')
        else: print(json.dumps(res,default=str))
        sys.exit(0)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(json.dumps({"error":f"No se pudo conectar a PostgreSQL: {e}"}))
        sys.exit(1)

    datos_certificados = []; errores = []; no_certs = 0; total = len(archivos)

    for i, archivo in enumerate(archivos,1):
        ext = Path(archivo).suffix.lower()
        if ext in ('.xlsx','.xls'):
            datos, error = extraer_datos_excel(archivo)
        else:
            continue  # ignora PDFs

        if error:
            errores.append({"archivo":archivo,"error":error})
        elif datos:
            datos_certificados.append(datos)
        else:
            no_certs+=1

        if i%50==0:
            print(f"Procesados {i}/{total} archivos...", file=sys.stderr)

    exitosos, omitidos = insertar_certificados(conn, datos_certificados, args.empleado)
    conn.close()

    res = {
        "total":total,
        "exitosos":exitosos,
        "omitidos":omitidos,
        "fallidos":len(errores),
        "no_certificados":no_certs,
        "errores":errores[:50] if errores else []
    }
    if args.json_output:
        print('__JSON_START__'); print(json.dumps(res,default=str)); print('__JSON_END__')
    else: print(json.dumps(res,default=str))