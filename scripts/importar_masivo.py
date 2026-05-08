"""
scripts/importar_masivo.py
SIDEC — Importación masiva de certificados (solo Excel)
Soporte bilingüe español/inglés + formatos abreviados.
Búsqueda adaptativa de hoja de portada.
Validación flexible de campos mínimos (7 campos).
Incluye listas de archivos exitosos, omitidos y no válidos.
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
            txt = str(clave.value)
            if ':' in txt:
                partes = txt.split(':', 1)
                val = partes[1].strip()
                if val and len(val) > 1:
                    return val
    return None

def buscar_valor_multilenguaje(hoja, etiquetas_es, etiquetas_en=None):
    val = buscar_valor_en_fila(hoja, etiquetas_es)
    if val: return val, None
    if etiquetas_en:
        val = buscar_valor_en_fila(hoja, etiquetas_en)
        if val: return val, None
    return None, f"No se encontró: {', '.join(etiquetas_es + (etiquetas_en or []))}"

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

def extraer_numero_informe(ws, ruta_archivo, identificacion_extraida=None):
    patron = r'(?:No\.?\s*)?([A-Za-z]{2,5}-\d+-\d+)'
    # 1. Celdas cercanas a "Hoja 1 de"
    for fila in ws.iter_rows():
        for celda in fila:
            if celda.value and isinstance(celda.value, str) and 'hoja 1 de' in celda.value.lower():
                for r in range(celda.row-1, celda.row+3):
                    for c in range(celda.column-2, celda.column+3):
                        try:
                            v = ws.cell(row=r, column=c).value
                            if v and isinstance(v, str):
                                m = re.search(patron, v)
                                if m:
                                    num = m.group(1)
                                    if not identificacion_extraida or num != identificacion_extraida:
                                        return num
                        except: continue
    # 2. Cualquier celda con patrón
    for fila in ws.iter_rows():
        for celda in fila:
            if celda.value and isinstance(celda.value, str):
                m = re.search(patron, celda.value)
                if m:
                    num = m.group(1)
                    if identificacion_extraida and num == identificacion_extraida:
                        continue
                    return num
    # 3. Nombre del archivo
    nombre = Path(ruta_archivo).stem
    m = re.search(patron, nombre)
    if m:
        num = m.group(1)
        if not identificacion_extraida or num != identificacion_extraida:
            return num
    return None

def extraer_datos_de_hoja(ws, ruta_archivo):
    identificacion, _ = buscar_valor_multilenguaje(ws,
        ["Identificación No","Identificacion No","IDENTIFICACIÓN","ID"],
        ["Identification","ID"])

    fecha_emision     = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de emisión","Date of issue","FECHA DE EMISIÓN"]))
    fecha_recepcion   = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de recepción","Reception date","FECHA DE RECEPCIÓN"]))
    fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha de calibración","Date of calibration","FECHA DE CALIBRACIÓN"]))
    if not fecha_calibracion:
        fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, ["Fecha del estudio","Study date","FECHA DEL ESTUDIO"]))

    numero_informe = extraer_numero_informe(ws, ruta_archivo, identificacion)

    nombre_cliente, _ = buscar_valor_multilenguaje(ws,
        ["Nombre del cliente","Cliente","NOMBRE DEL CLIENTE","CLIENTE"],
        ["Customer name","Client name"])
    descripcion, _ = buscar_valor_multilenguaje(ws,
        ["Descripción del instrumento","Descripción","DESCRIPCIÓN","DESCRIPCION"],
        ["Instrument description","Description"])

    numero_serie, _ = buscar_valor_multilenguaje(ws,
        ["No. De Serie","No. de serie","NO. DE SERIE","NÚMERO DE SERIE"],
        ["Serial number","Serial No"])
    modelo, _ = buscar_valor_multilenguaje(ws, ["Modelo","MODELO"], ["Model"])
    marca, _ = buscar_valor_multilenguaje(ws, ["Marca","MARCA"], ["Manufacturer","Brand"])
    magnitud, _ = buscar_valor_multilenguaje(ws,
        ["Magnitud evaluada","MAGNITUD EVALUADA","MAGNITUD DE EVALUADA"],
        ["Evaluated quality","Magnitude"])
    resultado, _ = buscar_valor_multilenguaje(ws,
        ["Resultado de calibración","Resultado del estudio","RESULTADO DE CALIBRACIÓN"],
        ["Calibration result","Study result"])
    lugar, _ = buscar_valor_multilenguaje(ws,
        ["Lugar de la calibración","Lugar del estudio","LUGAR DE LA CALIBRACIÓN"],
        ["Place of calibration","Study place"])
    calibro, _ = buscar_valor_multilenguaje(ws,
        ["Calibró","Realizó","CALIBRÓ"], ["Calibrated by","Done by"])
    aprobo, _ = buscar_valor_multilenguaje(ws, ["Aprobó","APROBÓ"], ["Approved by"])
    temperatura = buscar_valor_multilenguaje(ws,
        ["Temperatura","TEMPERATURA","TEMPERATURE"], ["Temperature"])[0] or None
    humedad = buscar_valor_multilenguaje(ws,
        ["Humedad Relativa","HUMEDAD RELATIVA","Humedad","HUMIDITY RELATIVE"],
        ["Relative Humidity","Humidity"])[0] or None
    metodo = buscar_valor_multilenguaje(ws,
        ["Método utilizado","Método Utilizado","MÉTODO UTILIZADO"], ["Used method"])[0] or None
    incertidumbre = buscar_valor_multilenguaje(ws,
        ["Incertidumbre","INCERTIDUMBRE"], ["Uncertainty"])[0] or None

    anio = None
    if fecha_emision: anio = fecha_emision.year
    elif numero_informe:
        m = re.search(r'-(\d{2})$', numero_informe)
        if m: anio = 2000+int(m.group(1)) if int(m.group(1))<=50 else 1900+int(m.group(1))
    if not anio: anio = datetime.now().year

    return {
        "numero_informe": numero_informe,
        "anio_emision": anio,
        "nombre_cliente": nombre_cliente,
        "descripcion_instrumento": descripcion,
        "alcance": buscar_valor_en_fila(ws, ["Alcance de Medición","Alcance","ALCANCE DE MEDICIÓN","Range"]),
        "numero_serie": numero_serie,
        "identificacion": identificacion,
        "modelo": modelo,
        "marca": marca,
        "magnitud_evaluada": magnitud,
        "resultado_calibracion": resultado,
        "incertidumbre": incertidumbre,
        "temperatura": temperatura,
        "humedad_relativa": humedad,
        "metodo_utilizado": metodo,
        "lugar_calibracion": lugar,
        "calibrado_por": calibro,
        "aprobado_por": aprobo,
        "fecha_recepcion": fecha_recepcion,
        "fecha_calibracion": fecha_calibracion,
        "fecha_emision": fecha_emision,
    }

def extraer_datos_excel(ruta_archivo):
    ext = Path(ruta_archivo).suffix.lower()
    if ext == '.xls' and not ruta_archivo.lower().endswith('.xlsx'):
        return extraer_datos_xls(ruta_archivo)

    try:
        wb = openpyxl.load_workbook(ruta_archivo, data_only=True)

        for nombre in wb.sheetnames:
            if any(p in nombre.lower() for p in ['portada', 'informe de calibración', 'certificado']):
                ws = wb[nombre]
                datos = extraer_datos_de_hoja(ws, ruta_archivo)
                if datos:
                    datos["ruta_archivo_origen"] = ruta_archivo
                    datos["fecha_importacion"] = datetime.now()
                    return datos, None

        for nombre in wb.sheetnames:
            ws = wb[nombre]
            datos = extraer_datos_de_hoja(ws, ruta_archivo)
            if datos:
                datos["ruta_archivo_origen"] = ruta_archivo
                datos["fecha_importacion"] = datetime.now()
                return datos, None

        return None, "No se encontró hoja de portada ni datos en ninguna hoja."

    except Exception as e:
        return None, f"Error Excel: {str(e)}"

def extraer_datos_xls(ruta_archivo):
    if not TIENE_XLRD:
        return None, "xlrd no instalado."
    try:
        wb = xlrd.open_workbook(ruta_archivo)
        for n in wb.sheet_names():
            ws = wb.sheet_by_name(n)
            datos = _extraer_xls_desde_ws(ws, ruta_archivo)
            if datos[0] is not None:
                return datos
        return None, "No se encontraron datos en ninguna hoja"
    except Exception as e:
        return None, f"Error XLS: {str(e)}"

def _extraer_xls_desde_ws(ws, ruta_archivo):
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
                txt = str(clave.value)
                if ':' in txt:
                    val = txt.split(':',1)[1].strip()
                    if val and len(val)>1: return val
        return None

    def multileng_xls(es, en=None):
        v = buscar_fila(es)
        if v: return v, None
        if en:
            v = buscar_fila(en)
            if v: return v, None
        return None, f"No se encontró: {', '.join(es+(en or []))}"

    identificacion = multileng_xls(["Identificación No","Identificacion No"],["Identification"])[0]

    nombre_cliente, _ = multileng_xls(["Nombre del cliente","Cliente"],["Customer name","Client name"])
    descripcion, _ = multileng_xls(["Descripción del instrumento","Descripción"],["Instrument description"])
    if not nombre_cliente and not descripcion:
        return None, "Falta cliente e instrumento"

    fecha_em = limpiar_fecha(buscar_fila(["Fecha de emisión","Date of issue"]))
    fecha_rec = limpiar_fecha(buscar_fila(["Fecha de recepción","Reception date"]))
    fecha_cal = limpiar_fecha(buscar_fila(["Fecha de calibración","Date of calibration"]))
    if not fecha_cal: fecha_cal = limpiar_fecha(buscar_fila(["Fecha del estudio","Study date"]))

    num_info = None
    for fila in filas:
        for celda in fila:
            try:
                m = re.search(r'([A-Za-z]{2,5}-\d+-\d+)', str(celda.value) if celda.value else '')
                if m:
                    cand = m.group(1)
                    if not identificacion or cand != identificacion:
                        num_info = cand; break
            except: continue
        if num_info: break
    if not num_info:
        nombre = Path(ruta_archivo).stem
        match = re.search(r'([A-Za-z]{2,5}-\d+-\d+)', nombre)
        if match:
            cand = match.group(1)
            if not identificacion or cand != identificacion:
                num_info = cand

    anio = None
    if fecha_em: anio=fecha_em.year
    elif num_info:
        m = re.search(r'-(\d{2})$', num_info)
        if m: anio = 2000+int(m.group(1)) if int(m.group(1))<=50 else 1900+int(m.group(1))
    if not anio:
        m = re.search(r'20[1-3]\d', ruta_archivo); 
        if m: anio=int(m.group())
    if not anio: anio=datetime.now().year

    return {
        "numero_informe": num_info,
        "anio_emision": anio,
        "nombre_cliente": nombre_cliente,
        "descripcion_instrumento": descripcion,
        "alcance": buscar_fila(["Alcance de Medición","Alcance","Range"]),
        "numero_serie": multileng_xls(["No. De Serie","No. de serie"],["Serial number"])[0],
        "identificacion": identificacion,
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
    }, None

# ── Validación ─────────────────────────────────────────
CAMPOS_PRINCIPALES = [
    'numero_informe', 'nombre_cliente', 'descripcion_instrumento',
    'alcance', 'numero_serie', 'identificacion', 'modelo', 'marca',
    'magnitud_evaluada', 'fecha_emision', 'fecha_calibracion',
    'lugar_calibracion', 'calibrado_por', 'aprobado_por'
]

def es_certificado_valido(datos):
    if not datos.get('numero_informe'):
        return False
    presentes = sum(1 for campo in CAMPOS_PRINCIPALES if datos.get(campo))
    return presentes >= 7

# ── Escaneo ────────────────────────────────────────────
def escanear_carpeta(carpeta, anio_filtro=None):
    archivos = []
    raiz = Path(carpeta)
    if not raiz.exists(): return []
    for ruta in raiz.rglob('*'):
        if not ruta.is_file() or ruta.name.startswith('~$'): continue
        ext = ruta.suffix.lower()
        if ext not in ('.xlsx','.xls'): continue
        if anio_filtro:
            m = re.search(r'20[1-3]\d', str(ruta))
            if m and int(m.group())!=int(anio_filtro): continue
        archivos.append(str(ruta))
    return sorted(archivos)

# ── Inserción con recolección de omitidos ─────────────
def insertar_certificados(conn, datos_lista, empleado=None):
    cursor = conn.cursor()
    columnas = [
        'numero_informe','anio_emision','nombre_cliente',
        'descripcion_instrumento','alcance','numero_serie',
        'identificacion','modelo','marca','magnitud_evaluada',
        'resultado_calibracion','incertidumbre','temperatura','humedad_relativa',
        'metodo_utilizado','lugar_calibracion',
        'calibrado_por','aprobado_por',
        'fecha_recepcion','fecha_calibracion','fecha_emision',
        'ruta_archivo_origen','fecha_importacion','importado_por'
    ]
    exitosos = 0
    omitidos = 0
    archivos_omitidos = []
    errores = []
    for datos in datos_lista:
        try:
            if empleado: datos['importado_por'] = empleado
            vals = [datos.get(c) for c in columnas]
            cursor.execute("SAVEPOINT sp")
            try:
                cursor.execute(f"""
                    INSERT INTO certificados ({', '.join(columnas)})
                    VALUES ({','.join(['%s']*len(columnas))})
                    ON CONFLICT (numero_informe) DO NOTHING
                """, vals)
                if cursor.rowcount > 0:
                    exitosos += 1
                else:
                    omitidos += 1
                    archivos_omitidos.append(os.path.basename(datos.get("ruta_archivo_origen", "")))
                cursor.execute("RELEASE SAVEPOINT sp")
            except Exception as insert_err:
                cursor.execute("ROLLBACK TO SAVEPOINT sp")
                errores.append({"archivo": datos.get("ruta_archivo_origen", ""), "error": str(insert_err)})
                print(f"Error insertando {datos.get('numero_informe', '?')}: {insert_err}", file=sys.stderr)
        except Exception as e:
            errores.append({"archivo": datos.get("ruta_archivo_origen", ""), "error": str(e)})
            print(f"Error preparando inserción: {e}", file=sys.stderr)
    conn.commit()
    cursor.close()
    return exitosos, omitidos, archivos_omitidos, errores

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

    datos_validos = []
    archivos_exitosos = []
    archivos_no_validos = []
    errores_extraccion = []
    no_certs = 0
    total = len(archivos)

    for i, archivo in enumerate(archivos,1):
        ext = Path(archivo).suffix.lower()
        if ext in ('.xlsx','.xls'):
            datos, error = extraer_datos_excel(archivo)
        else:
            continue

        if error:
            errores_extraccion.append({"archivo":archivo,"error":error})
        elif datos:
            if es_certificado_valido(datos):
                datos_validos.append(datos)
                archivos_exitosos.append(os.path.basename(archivo))
            else:
                archivos_no_validos.append(os.path.basename(archivo))
                no_certs += 1
        else:
            archivos_no_validos.append(os.path.basename(archivo))
            no_certs += 1

        # Emitir progreso cada 5 archivos (o en el primero y último)
        if i % 5 == 0 or i == total:
            print(f"Procesados {i}/{total} archivos...", file=sys.stderr)

    exitosos, omitidos, archivos_omitidos, errores_insercion = insertar_certificados(conn, datos_validos, args.empleado)
    conn.close()

    todos_errores = errores_extraccion + errores_insercion

    res = {
        "total":total,
        "exitosos":exitosos,
        "omitidos":omitidos,
        "fallidos":len(todos_errores),
        "no_certificados":no_certs,
        "archivos_exitosos": archivos_exitosos,
        "archivos_omitidos": archivos_omitidos,
        "archivos_no_validos": archivos_no_validos,
        "errores":todos_errores[:50] if todos_errores else []
    }
    if args.json_output:
        print('__JSON_START__'); print(json.dumps(res,default=str)); print('__JSON_END__')
    else: print(json.dumps(res,default=str))