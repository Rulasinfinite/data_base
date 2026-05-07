"""
scripts/extraer_pdf_sidec.py
Módulo de extracción específico para certificados SIDEC
Se importa desde importar_masivo.py
"""
import re
from datetime import datetime

def extraer_certificado_sidec(texto: str) -> dict:
    """
    Extrae todos los campos de un certificado SIDEC desde texto plano.
    Funciona con el formato exacto del PDF (ej: LMD-143-25)
    """
    lines = texto.split('\n')

    def buscar_valor(etiquetas):
        """Busca el valor después de una etiqueta en el texto."""
        for i, line in enumerate(lines):
            line_clean = line.strip()
            for etiqueta in etiquetas:
                if etiqueta.lower() in line_clean.lower():
                    # 1) Valor en la misma línea después de ':'
                    partes = re.split(r':\s*', line_clean, maxsplit=1)
                    if len(partes) > 1:
                        val = partes[1].strip()
                        # Quitar texto en inglés que viene junto (Customer name:, etc)
                        val = re.split(r'\s{3,}', val)[0].strip()
                        if val and len(val) > 1 and not val.endswith(':'):
                            return val
                    # 2) Valor en la línea siguiente (ignorar etiquetas en inglés)
                    for j in range(i+1, min(i+3, len(lines))):
                        sig = lines[j].strip()
                        # Ignorar líneas vacías y etiquetas en inglés
                        english_tags = ['customer','address','attention','instrument',
                                       'serial','model','manufacturer','evaluated',
                                       'method','place','reception','calibration',
                                       'date','uncertainty','result','conditions']
                        es_etiqueta_en = any(t in sig.lower() for t in english_tags) and ':' in sig
                        if sig and not es_etiqueta_en and len(sig) > 1:
                            return sig
        return None

    # ── Número de informe ──────────────────────────────────
    numero = None
    patrones_num = [
        r'No\.\s+(LM[A-Z]-\d+-\d+)',      # No. LMD-143-25
        r'No\.\s+([A-Z]{2,5}-\d+-\d+)',   # Formato general
        r'N[uú]m(?:ero)?\.?\s+([A-Z0-9\-]{5,})',
    ]
    for p in patrones_num:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            numero = m.group(1).strip()
            break

    # ── Año desde número de informe (LMD-143-25 → 2025) ───
    anio = None
    if numero:
        m_anio = re.search(r'-(\d{2})$', numero)
        if m_anio:
            sufijo = int(m_anio.group(1))
            anio = 2000 + sufijo if sufijo <= 50 else 1900 + sufijo

    # ── Fechas ────────────────────────────────────────────
    def limpiar_fecha(val):
        if not val: return None
        formatos = ['%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%m/%d/%Y']
        for fmt in formatos:
            try:
                return datetime.strptime(val.strip()[:10], fmt).date()
            except: continue
        return None

    fecha_emision     = limpiar_fecha(buscar_valor(["Fecha de emisión", "Date of issue"]))
    fecha_recepcion   = limpiar_fecha(buscar_valor(["Fecha de recepción", "Reception date"]))
    fecha_calibracion = limpiar_fecha(buscar_valor(["Fecha de calibración", "Date of calibration"]))

    # Si no se obtuvo año del número, usar año de fecha de emisión
    if not anio and fecha_emision:
        anio = fecha_emision.year

    # ── Condiciones ambientales ────────────────────────────
    temp = buscar_valor(["Temperatura", "Temperature"])
    hum  = buscar_valor(["Humedad", "Humidity", "Relative Humidity"])

    # Limpiar temperatura (solo el valor numérico con unidad)
    if temp:
        m_temp = re.search(r'(\d+\s*°?\s*C[\s±°\d\.]*)', temp)
        if m_temp: temp = m_temp.group(1).strip()

    return {
        "numero_informe":          numero,
        "anio_emision":            anio,
        "nombre_cliente":          buscar_valor(["Nombre del cliente", "Customer name"]),
        "direccion":               buscar_valor(["Dirección", "Address"]),
        "atencion_a":              buscar_valor(["Atención a", "Attention to"]),
        "descripcion_instrumento": buscar_valor(["Descripción del instrumento", "Instrument description"]),
        "alcance":                 buscar_valor(["Alcance de Medición", "Alcance"]),
        "numero_serie":            buscar_valor(["No. De Serie", "No. de serie", "Serial number"]),
        "identificacion":          buscar_valor(["Identificación No", "Identificacion No"]),
        "modelo":                  buscar_valor(["Modelo", "Model"]),
        "marca":                   buscar_valor(["Marca", "Manufacturer"]),
        "magnitud_evaluada":       buscar_valor(["Magnitud evaluada", "Evaluated quality"]),
        "resultado_calibracion":   buscar_valor(["Resultado de calibración", "Calibration result"]),
        "incertidumbre":           buscar_valor(["Incertidumbre", "Uncertainty"]),
        "temperatura":             temp,
        "humedad_relativa":        hum,
        "metodo_utilizado":        buscar_valor(["Método utilizado", "Used method"]),
        "lugar_calibracion":       buscar_valor(["Lugar de la calibración", "Place of calibration"]),
        "calibrado_por":           buscar_valor(["Calibró", "Calibrated by"]),
        "aprobado_por":            buscar_valor(["Aprobó", "Approved by"]),
        "fecha_recepcion":         fecha_recepcion,
        "fecha_calibracion":       fecha_calibracion,
        "fecha_emision":           fecha_emision,
    }


def es_certificado_sidec(datos: dict) -> bool:
    """Verifica que el dict tenga suficientes campos para ser un certificado válido."""
    campos_clave = [
        'numero_informe', 'nombre_cliente',
        'descripcion_instrumento', 'fecha_emision',
        'magnitud_evaluada', 'marca'
    ]
    llenos = sum(1 for c in campos_clave if datos.get(c))
    return llenos >= 2
