"""
scripts/importar_masivo.py
SIDEC — Importación masiva de certificados (solo Excel)
Extracción robusta para archivos antiguos y nuevos.
Se omiten 'Calibrado por' y 'Aprobado por'.
Soporte para .xls antiguos con celdas combinadas.
"""

import os, sys, re, json, argparse
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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

import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

try:
    import xlrd
    TIENE_XLRD = True
except ImportError:
    TIENE_XLRD = False

DB_CONFIG = {
    'host':     os.getenv('DB_HOST',     'localhost'),
    'port':     int(os.getenv('DB_PORT', 5432)),
    'dbname':   os.getenv('DB_NAME',     'sidec_db'),
    'user':     os.getenv('DB_USER',     'postgres'),
    'password': os.getenv('DB_PASSWORD', 'sidecmexico'),
}

# ──────────── Helpers de extracción ────────────
def _limpiar_valor(valor):
    """Limpia un valor de celda devolviendo siempre un string o None."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.strftime('%Y-%m-%d')
    val_str = str(valor).strip()
    return val_str if val_str else None

def _obtener_valor_celda(ws, row, col):
    """Obtiene valor de una celda de forma segura (para openpyxl)."""
    try:
        return ws.cell(row=row, column=col).value
    except:
        return None

def _extraer_desde_lineas(texto, etiqueta):
    """
    Busca la etiqueta en un texto multilínea y devuelve el valor asociado.
    """
    lineas = texto.split('\n')
    for linea in lineas:
        limpia = linea.strip().lstrip('-•·*').strip()
        if etiqueta.lower() in limpia.lower():
            if ':' in limpia:
                _, val = limpia.split(':', 1)
                val = val.strip()
                if val:
                    return val
            else:
                idx = limpia.lower().find(etiqueta.lower())
                if idx != -1:
                    resto = limpia[idx + len(etiqueta):].strip()
                    if resto:
                        return resto
    return None

def buscar_valor_en_fila(hoja, etiquetas, max_filas_extra=8):
    """
    Busca una etiqueta en una fila y devuelve el valor asociado.
    Estrategia mejorada para .xls antiguos:
      0. Si la celda tiene saltos de línea, extraer la línea exacta con la etiqueta.
      1. Después de ':' en la MISMA celda.
      2. Texto inmediato después de la etiqueta dentro de la misma celda.
      3. Otra celda de la MISMA fila que NO sea etiqueta pura.
      4. Celda en la misma fila, columna siguiente.
      5. Filas siguientes dentro de `max_filas_extra`.
    """
    ETIQUETAS_CONOCIDAS = {
        'nombre del cliente', 'customer name', 'client name', 'cliente',
        'dirección', 'direccion', 'address',
        'descripción del instrumento', 'instrument description', 'description',
        'alcance de medición', 'alcance', 'range',
        'no. de serie', 'serial number', 'serial no',
        'identificación no', 'identificacion no', 'identification',
        'modelo', 'model',
        'marca', 'manufacturer', 'brand',
        'magnitud evaluada', 'evaluated quality', 'magnitude',
        'resultado de calibración', 'calibration result',
        'incertidumbre', 'uncertainty',
        'temperatura', 'temperature',
        'humedad relativa', 'relative humidity', 'humidity',
        'fecha de emisión', 'date of issue',
        'fecha de recepción', 'reception date',
        'fecha de calibración', 'date of calibration',
        'método utilizado', 'used method',
        'lugar de la calibración', 'place of calibration',
        'atención a', 'atencion a', 'attention to',
    }

    def _es_solo_etiqueta(texto):
        t = texto.strip().lower().rstrip(':').strip()
        return t in ETIQUETAS_CONOCIDAS or len(t) < 3

    for fila in hoja.iter_rows():
        for celda in fila:
            if celda.value and isinstance(celda.value, str):
                txt = str(celda.value)
                for eti in etiquetas:
                    if eti.lower() in txt.lower():
                        # 0. Si tiene saltos de línea, extraer línea específica
                        if '\n' in txt:
                            val = _extraer_desde_lineas(txt, eti)
                            if val:
                                return val
                        # 1. Después de ':'
                        if ':' in txt:
                            partes = txt.split(':', 1)
                            val = partes[1].strip() if len(partes) > 1 else None
                            if val and len(val) > 1:
                                return val.split('\n')[0].strip()
                        # 2. Texto después de la etiqueta
                        idx = txt.lower().find(eti.lower())
                        if idx != -1:
                            resto = txt[idx + len(eti):].strip()
                            if resto.startswith(':'):
                                resto = resto[1:].strip()
                            if resto and len(resto) > 1:
                                return resto.split('\n')[0].strip()
                        # 3. Otra celda de la misma fila (no etiqueta pura)
                        for c in fila:
                            if c != celda and c.value:
                                val = _limpiar_valor(c.value)
                                if val and len(val) > 1 and not _es_solo_etiqueta(val):
                                    return val
                        # 4. Celda siguiente en la misma fila (columna+1)
                        try:
                            sig = hoja.cell(row=celda.row, column=celda.column+1).value
                            if sig and not _es_solo_etiqueta(str(sig)):
                                return _limpiar_valor(sig)
                        except:
                            pass
                        # 5. Filas siguientes
                        for offset in range(1, max_filas_extra+1):
                            try:
                                val = hoja.cell(row=celda.row+offset, column=celda.column).value
                                if val:
                                    val = _limpiar_valor(val)
                                    if val and len(val) > 1 and not _es_solo_etiqueta(val):
                                        return val
                                # También probar en columna+1
                                val2 = hoja.cell(row=celda.row+offset, column=celda.column+1).value
                                if val2:
                                    val2 = _limpiar_valor(val2)
                                    if val2 and len(val2) > 1 and not _es_solo_etiqueta(val2):
                                        return val2
                            except:
                                continue
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
    # Buscar cerca de "Hoja 1 de"
    for fila in ws.iter_rows():
        for celda in fila:
            if celda.value and isinstance(celda.value, str) and 'hoja 1 de' in celda.value.lower():
                for r in range(celda.row-1, celda.row+3):
                    for c in range(celda.column-2, celda.column+3):
                        try:
                            v = _obtener_valor_celda(ws, r, c)
                            if v and isinstance(v, str):
                                m = re.search(patron, v)
                                if m:
                                    num = m.group(1)
                                    if not identificacion_extraida or num != identificacion_extraida:
                                        return num
                        except: continue
    # Cualquier celda
    for fila in ws.iter_rows():
        for celda in fila:
            if celda.value and isinstance(celda.value, str):
                m = re.search(patron, celda.value)
                if m:
                    num = m.group(1)
                    if not identificacion_extraida or num != identificacion_extraida:
                        return num
    # Nombre del archivo
    nombre = Path(ruta_archivo).stem
    m = re.search(patron, nombre)
    if m:
        num = m.group(1)
        if not identificacion_extraida or num != identificacion_extraida:
            return num
    return nombre if nombre else None

def extraer_datos_de_hoja(ws, ruta_archivo):
    identificacion, _ = buscar_valor_multilenguaje(ws,
        ["Identificación No","Identificacion No","IDENTIFICACIÓN","ID"],
        ["Identification","ID"])

    # Fechas
    fecha_emision     = limpiar_fecha(buscar_valor_en_fila(ws, [
        "Fecha de emisión","Fecha de Emisión","Date of issue","FECHA DE EMISIÓN",
        "Fecha de emision","Fecha Emisión","Fecha Emision"
    ], max_filas_extra=8))
    fecha_recepcion   = limpiar_fecha(buscar_valor_en_fila(ws, [
        "Fecha de recepción","Fecha de Recepción","Reception date","FECHA DE RECEPCIÓN",
        "Fecha de recepcion","Fecha Recepción","Fecha Recepcion"
    ], max_filas_extra=8))
    fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, [
        "Fecha de calibración","Fecha de Calibración","Date of calibration","FECHA DE CALIBRACIÓN",
        "Date of calibration finish","Fecha de calibracion","Fecha Calibración","Fecha Calibracion"
    ], max_filas_extra=8))
    if not fecha_calibracion:
        fecha_calibracion = limpiar_fecha(buscar_valor_en_fila(ws, [
            "Fecha del estudio","Study date","FECHA DEL ESTUDIO"
        ], max_filas_extra=8))

    numero_informe = extraer_numero_informe(ws, ruta_archivo, identificacion)

    nombre_cliente, _ = buscar_valor_multilenguaje(ws,
        ["Nombre del cliente","Cliente","NOMBRE DEL CLIENTE","CLIENTE"],
        ["Customer name","Client name"])
    direccion = buscar_valor_en_fila(ws, ["Dirección","Direccion","Address","DIRECCIÓN"], max_filas_extra=4)
    atencion_a = buscar_valor_en_fila(ws, ["Atención a","Atencion a","Attention to","ATENCIÓN A"])

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

    # Alcance
    alcance = buscar_valor_en_fila(ws, [
        "Alcance de Medición","Alcance de medicion","ALCANCE DE MEDICIÓN",
        "Alcance de Medicion","Range of measurement","Range"
    ], max_filas_extra=8)
    if not alcance:
        # Buscar patrones de rango numérico
        for fila in ws.iter_rows():
            for celda in fila:
                if celda.value and isinstance(celda.value, str):
                    m = re.search(r'(\d+\s*(?:kg|g|m|mm|°C|bar|psi|N|l|L|HRC)?\s*(?:a|–|-|to)\s*\d+\s*(?:kg|g|m|mm|°C|bar|psi|N|l|L|HRC)?)', celda.value)
                    if m:
                        alcance = m.group(0).strip()
                        break
            if alcance: break

    # Temperatura
    temperatura = buscar_valor_en_fila(ws, [
        "Temperatura","TEMPERATURA","TEMPERATURE","Temperature"
    ], max_filas_extra=8)
    if not temperatura:
        for fila in ws.iter_rows():
            for celda in fila:
                if celda.value and isinstance(celda.value, str):
                    if 'temperatura' in celda.value.lower() or 'temperature' in celda.value.lower():
                        for r in range(celda.row, celda.row+5):
                            for c in range(celda.column-1, celda.column+5):
                                try:
                                    v = _obtener_valor_celda(ws, r, c)
                                    if v and isinstance(v, str) and '°C' in v:
                                        temperatura = v.strip()
                                        break
                                except: pass
                            if temperatura: break
                        if not temperatura:
                            for c in fila:
                                if c != celda and c.value and isinstance(c.value, str):
                                    m = re.search(r'\d+\s*°?\s*[Cc]', c.value)
                                    if m:
                                        temperatura = c.value.strip()
                                        break
                    if temperatura: break
            if temperatura: break

    # Humedad
    humedad = buscar_valor_en_fila(ws, [
        "Humedad Relativa","HUMEDAD RELATIVA","Humedad","HUMIDITY RELATIVE",
        "Relative Humidity","Humidity"
    ], max_filas_extra=8)
    if not humedad:
        for fila in ws.iter_rows():
            for celda in fila:
                if celda.value and isinstance(celda.value, str):
                    if 'humedad' in celda.value.lower() or 'humidity' in celda.value.lower():
                        for r in range(celda.row, celda.row+5):
                            for c in range(celda.column-1, celda.column+5):
                                try:
                                    v = _obtener_valor_celda(ws, r, c)
                                    if v and isinstance(v, str) and '%' in v:
                                        humedad = v.strip()
                                        break
                                except: pass
                            if humedad: break
                        if not humedad:
                            for c in fila:
                                if c != celda and c.value and isinstance(c.value, str) and '%' in c.value:
                                    humedad = c.value.strip()
                                    break
                    if humedad: break
            if humedad: break

    metodo = (buscar_valor_en_fila(ws, ["Método utilizado","Método Utilizado","MÉTODO UTILIZADO","Used method"], max_filas_extra=5) or
              (buscar_valor_multilenguaje(ws, ["Método utilizado"], ["Used method"])[0] if buscar_valor_multilenguaje(ws, ["Método utilizado"], ["Used method"])[0] else None))
    incertidumbre = (buscar_valor_en_fila(ws, ["Incertidumbre","INCERTIDUMBRE","Uncertainty"], max_filas_extra=5) or
                     (buscar_valor_multilenguaje(ws, ["Incertidumbre"], ["Uncertainty"])[0] if buscar_valor_multilenguaje(ws, ["Incertidumbre"], ["Uncertainty"])[0] else None))

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
        "direccion": direccion,
        "atencion_a": atencion_a,
        "descripcion_instrumento": descripcion,
        "alcance": alcance,
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
        "calibrado_por": None,
        "aprobado_por": None,
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

# ═══════════════ Funciones para .xls antiguo (mejoradas) ═══════════════
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
    """
    Extracción para hojas .xls usando xlrd.
    Implementa la misma lógica robusta que para openpyxl.
    """
    # Convertir a lista de listas para acceso fácil
    nrows = ws.nrows
    ncols = ws.ncols
    datos_crudos = []
    for r in range(nrows):
        fila = []
        for c in range(ncols):
            v = ws.cell_value(r,c)
            if isinstance(v, float) and v == int(v):
                v = str(int(v))
            elif isinstance(v, float):
                v = str(v)
            else:
                v = str(v) if v else None
            fila.append(v)
        datos_crudos.append(fila)

    # Función auxiliar para obtener valor como string
    def _get_val(row, col):
        if 0 <= row < nrows and 0 <= col < ncols:
            return datos_crudos[row][col]
        return None

    def _es_etiqueta_pura(texto):
        if not texto: return False
        t = texto.strip().lower().rstrip(':').strip()
        etiq = {
            'nombre del cliente', 'cliente', 'dirección', 'direccion', 'address',
            'descripción del instrumento', 'instrument description', 'alcance de medición',
            'alcance', 'range', 'no. de serie', 'serial number', 'identificación no',
            'identificacion no', 'modelo', 'marca', 'manufacturer', 'magnitud evaluada',
            'resultado de calibración', 'incertidumbre', 'temperatura', 'temperature',
            'humedad relativa', 'fecha de emisión', 'fecha de recepción', 'fecha de calibración',
            'método utilizado', 'lugar de la calibración', 'atención a'
        }
        return t in etiq or len(t) < 3

    def buscar_valor_xls(etiquetas, max_filas_extra=8):
        for r in range(nrows):
            for c in range(ncols):
                txt = _get_val(r,c)
                if not txt or not isinstance(txt, str):
                    continue
                for eti in etiquetas:
                    if eti.lower() in txt.lower():
                        # 0. Si tiene saltos de línea
                        if '\n' in txt:
                            val = _extraer_desde_lineas(txt, eti)
                            if val: return val
                        # 1. Después de ':'
                        if ':' in txt:
                            partes = txt.split(':', 1)
                            if len(partes) > 1:
                                val = partes[1].strip()
                                if val and len(val) > 1:
                                    return val.split('\n')[0].strip()
                        # 2. Texto después de la etiqueta
                        idx = txt.lower().find(eti.lower())
                        if idx != -1:
                            resto = txt[idx+len(eti):].strip()
                            if resto.startswith(':'):
                                resto = resto[1:].strip()
                            if resto and len(resto) > 1:
                                return resto.split('\n')[0].strip()
                        # 3. Otra celda en la misma fila
                        for cc in range(ncols):
                            if cc != c:
                                val = _get_val(r, cc)
                                if val and not _es_etiqueta_pura(val):
                                    return val
                        # 4. Columna siguiente
                        val_sig = _get_val(r, c+1)
                        if val_sig and not _es_etiqueta_pura(val_sig):
                            return val_sig
                        # 5. Filas siguientes
                        for offset in range(1, max_filas_extra+1):
                            val_bajo = _get_val(r+offset, c)
                            if val_bajo and not _es_etiqueta_pura(val_bajo):
                                return val_bajo
                            val_bajo2 = _get_val(r+offset, c+1)
                            if val_bajo2 and not _es_etiqueta_pura(val_bajo2):
                                return val_bajo2
        return None

    def multileng_xls(es, en=None):
        v = buscar_valor_xls(es)
        if v: return v, None
        if en:
            v = buscar_valor_xls(en)
            if v: return v, None
        return None, "no encontrado"

    # Extracción específica
    identificacion, _ = multileng_xls(["Identificación No","Identificacion No","IDENTIFICACIÓN","ID"], ["Identification","ID"])
    nombre_cliente, _ = multileng_xls(["Nombre del cliente","Cliente","NOMBRE DEL CLIENTE"], ["Customer name","Client name"])
    descripcion, _ = multileng_xls(["Descripción del instrumento","Descripción","DESCRIPCIÓN"], ["Instrument description"])
    direccion = buscar_valor_xls(["Dirección","Direccion","Address","DIRECCIÓN"])
    atencion_a = buscar_valor_xls(["Atención a","Atencion a","Attention to"])

    fecha_em = limpiar_fecha(buscar_valor_xls(["Fecha de emisión","Fecha de Emisión","Date of issue"], max_filas_extra=8))
    fecha_rec = limpiar_fecha(buscar_valor_xls(["Fecha de recepción","Fecha de Recepción","Reception date"], max_filas_extra=8))
    fecha_cal = limpiar_fecha(buscar_valor_xls(["Fecha de calibración","Fecha de Calibración","Date of calibration"], max_filas_extra=8))
    if not fecha_cal:
        fecha_cal = limpiar_fecha(buscar_valor_xls(["Fecha del estudio","Study date"], max_filas_extra=8))

    # Número de informe
    num_info = None
    patron = r'([A-Za-z]{2,5}-\d+-\d+)'
    for r in range(nrows):
        for c in range(ncols):
            txt = _get_val(r,c)
            if txt:
                m = re.search(patron, str(txt))
                if m:
                    cand = m.group(1)
                    if not identificacion or cand != identificacion:
                        num_info = cand
                        break
        if num_info: break
    if not num_info:
        nombre = Path(ruta_archivo).stem
        m = re.search(patron, nombre)
        num_info = m.group(1) if m else nombre

    anio = None
    if fecha_em: anio = fecha_em.year
    elif num_info:
        m = re.search(r'-(\d{2})$', num_info)
        if m: anio = 2000+int(m.group(1)) if int(m.group(1))<=50 else 1900+int(m.group(1))
    if not anio:
        m = re.search(r'20[1-3]\d', ruta_archivo)
        if m: anio = int(m.group())
    if not anio: anio = datetime.now().year

    alcance = buscar_valor_xls(["Alcance de Medición","Alcance de medicion","Range"], max_filas_extra=8)
    if not alcance:
        for r in range(nrows):
            for c in range(ncols):
                txt = _get_val(r,c)
                if txt and isinstance(txt, str):
                    m = re.search(r'(\d+\s*(?:kg|g|m|mm|°C|bar|psi|N|l|L|HRC)?\s*(?:a|–|-|to)\s*\d+\s*(?:kg|g|m|mm|°C|bar|psi|N|l|L|HRC)?)', txt)
                    if m:
                        alcance = m.group(0).strip()
                        break
            if alcance: break

    numero_serie, _ = multileng_xls(["No. De Serie","No. de serie","SERIAL"], ["Serial number"])
    modelo, _ = multileng_xls(["Modelo"], ["Model"])
    marca, _ = multileng_xls(["Marca"], ["Manufacturer","Brand"])
    magnitud, _ = multileng_xls(["Magnitud evaluada","MAGNITUD"], ["Evaluated quality"])
    resultado, _ = multileng_xls(["Resultado de calibración","Resultado del estudio"], ["Calibration result"])
    lugar, _ = multileng_xls(["Lugar de la calibración","Lugar del estudio"], ["Place of calibration"])
    metodo, _ = multileng_xls(["Método utilizado","MÉTODO"], ["Used method"])
    incertidumbre, _ = multileng_xls(["Incertidumbre","INCERTIDUMBRE"], ["Uncertainty"])
    temperatura = buscar_valor_xls(["Temperatura","TEMPERATURA","Temperature"], max_filas_extra=8)
    humedad = buscar_valor_xls(["Humedad Relativa","Humedad","Humidity"], max_filas_extra=8)

    return {
        "numero_informe": num_info,
        "anio_emision": anio,
        "nombre_cliente": nombre_cliente,
        "direccion": direccion,
        "atencion_a": atencion_a,
        "descripcion_instrumento": descripcion,
        "alcance": alcance,
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
        "calibrado_por": None,
        "aprobado_por": None,
        "fecha_recepcion": fecha_rec,
        "fecha_calibracion": fecha_cal,
        "fecha_emision": fecha_em,
        "ruta_archivo_origen": ruta_archivo,
        "fecha_importacion": datetime.now(),
    }, None

# ═══════════════ Validación e Inserción (sin cambios) ═══════════════
CAMPOS_PRINCIPALES = [
    'numero_informe', 'nombre_cliente', 'descripcion_instrumento',
    'alcance', 'numero_serie', 'identificacion', 'modelo', 'marca',
    'magnitud_evaluada', 'fecha_emision', 'fecha_calibracion',
    'lugar_calibracion'
]

def es_certificado_valido(datos):
    presentes = sum(1 for campo in CAMPOS_PRINCIPALES if datos.get(campo))
    return presentes >= 8

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

def resolver_clientes_en_lote(cursor, datos_lista):
    clientes = {}
    for d in datos_lista:
        nombre = d.get('nombre_cliente') or 'Cliente no identificado'
        direccion = d.get('direccion')
        atencion = d.get('atencion_a')
        if nombre not in clientes:
            clientes[nombre] = {'nombre': nombre, 'direccion': direccion, 'atencion': atencion}
        else:
            if not clientes[nombre]['direccion'] and direccion:
                clientes[nombre]['direccion'] = direccion
            if not clientes[nombre]['atencion'] and atencion:
                clientes[nombre]['atencion'] = atencion

    nombres_unicos = list(clientes.keys())
    cursor.execute("SELECT nombre, id FROM clientes WHERE nombre = ANY(%s)", (nombres_unicos,))
    existentes = {row[0]: row[1] for row in cursor.fetchall()}

    nuevos_nombres = [n for n in nombres_unicos if n not in existentes]
    if nuevos_nombres:
        inserts = [(clientes[n]['nombre'], clientes[n]['direccion'], clientes[n]['atencion']) for n in nuevos_nombres]
        execute_values(cursor,
            "INSERT INTO clientes (nombre, direccion, atencion_a) VALUES %s ON CONFLICT (nombre) DO UPDATE SET direccion = EXCLUDED.direccion, atencion_a = EXCLUDED.atencion_a",
            inserts
        )
        cursor.execute("SELECT nombre, id FROM clientes WHERE nombre = ANY(%s)", (nuevos_nombres,))
        existentes.update({row[0]: row[1] for row in cursor.fetchall()})

    for d in datos_lista:
        nombre = d.get('nombre_cliente') or 'Cliente no identificado'
        d['cliente_id'] = existentes[nombre]
        if not d.get('numero_informe'):
            d['numero_informe'] = Path(d.get('ruta_archivo_origen', '')).stem

def insertar_certificados(conn, datos_lista, empleado=None):
    if not datos_lista:
        return 0, 0, [], []

    cursor = conn.cursor()
    resolver_clientes_en_lote(cursor, datos_lista)

    if empleado:
        for d in datos_lista:
            d['importado_por'] = empleado

    columnas = [
        'numero_informe','anio_emision','cliente_id',
        'descripcion_instrumento','alcance','numero_serie',
        'identificacion','modelo','marca','magnitud_evaluada',
        'resultado_calibracion','incertidumbre','temperatura','humedad_relativa',
        'metodo_utilizado','lugar_calibracion',
        'calibrado_por','aprobado_por',
        'fecha_recepcion','fecha_calibracion','fecha_emision',
        'estado','fecha_vencimiento',
        'ruta_archivo_origen','fecha_importacion','importado_por'
    ]

    combinaciones = [(d['numero_informe'], d['cliente_id'], d.get('marca')) for d in datos_lista]
    cursor.execute(
        "SELECT numero_informe, cliente_id, marca FROM certificados WHERE (numero_informe, cliente_id, marca) IN %s",
        (tuple(combinaciones),)
    )
    existentes = set((row[0], row[1], row[2]) for row in cursor.fetchall())

    nuevos = []
    duplicados = []
    for d in datos_lista:
        clave = (d['numero_informe'], d['cliente_id'], d.get('marca'))
        if clave in existentes:
            duplicados.append(d)
        else:
            nuevos.append(d)

    errores = []
    if nuevos:
        try:
            valores = [tuple(d.get(c) for c in columnas) for d in nuevos]
            execute_values(cursor,
                f"INSERT INTO certificados ({', '.join(columnas)}) VALUES %s "
                f"ON CONFLICT (numero_informe, cliente_id, marca) DO NOTHING",
                valores
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            errores.append({"archivo": "lote", "error": str(e)})
            print(f"Error en inserción masiva: {e}", file=sys.stderr)

    cursor.close()
    exitosos = len(nuevos)
    omitidos = len(duplicados)
    archivos_omitidos = [Path(d.get('ruta_archivo_origen', '')).name for d in duplicados]
    return exitosos, omitidos, archivos_omitidos, errores

# ── MAIN ──
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

    max_workers = min(4, total) if total > 0 else 1
    completados = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extraer_datos_excel, archivo): archivo for archivo in archivos}

        for future in as_completed(futures):
            archivo = futures[future]
            completados += 1

            try:
                datos, error = future.result()
            except Exception as e:
                datos = None
                error = str(e)

            print(f"Procesando: {archivo}", file=sys.stderr, flush=True)

            if error:
                errores_extraccion.append({"archivo": archivo, "error": error})
            elif datos:
                if not datos.get('numero_informe'):
                    datos['numero_informe'] = os.path.basename(archivo).rsplit('.', 1)[0]
                if es_certificado_valido(datos):
                    datos_validos.append(datos)
                    archivos_exitosos.append(os.path.basename(archivo))
                else:
                    archivos_no_validos.append(os.path.basename(archivo))
                    no_certs += 1
            else:
                archivos_no_validos.append(os.path.basename(archivo))
                no_certs += 1

            if completados % 5 == 0 or completados == 1 or completados == total:
                print(f"Procesados {completados}/{total} archivos...", file=sys.stderr, flush=True)

    exitosos, omitidos, archivos_omitidos, errores_insercion = insertar_certificados(conn, datos_validos, args.empleado)
    conn.close()

    todos_errores = errores_extraccion + errores_insercion

    res = {
        "total": total,
        "exitosos": exitosos,
        "omitidos": omitidos,
        "fallidos": len(todos_errores),
        "no_certificados": no_certs,
        "archivos_exitosos": archivos_exitosos,
        "archivos_omitidos": archivos_omitidos,
        "archivos_no_validos": archivos_no_validos,
        "errores": todos_errores[:50] if todos_errores else []
    }
    if args.json_output:
        print('__JSON_START__')
        print(json.dumps(res, default=str))
        print('__JSON_END__')
    else:
        print(json.dumps(res, default=str))