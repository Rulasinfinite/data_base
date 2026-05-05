"""
scripts/diagnostico_pdf.py
Prueba de lectura de un certificado PDF de SIDEC
Uso: python diagnostico_pdf.py
"""
import sys
import re

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber no instalado.")
    print("Ejecuta: python -m pip install pdfplumber")
    sys.exit(1)

# ── CAMBIA ESTA RUTA AL PDF QUE QUIERES PROBAR ──────────────
RUTA_PDF = r'C:\Users\Rulas\OneDrive\Documentos\hola\certificado.pdf'
# ────────────────────────────────────────────────────────────

print("=" * 60)
print("  SIDEC — Diagnóstico de lectura PDF")
print("=" * 60)
print(f"\nArchivo: {RUTA_PDF}\n")

try:
    with pdfplumber.open(RUTA_PDF) as pdf:
        print(f"Páginas encontradas: {len(pdf.pages)}\n")

        # Extraer texto de las primeras 2 páginas
        texto_total = ""
        for i, page in enumerate(pdf.pages[:2]):
            texto = page.extract_text()
            if texto:
                texto_total += texto + "\n"
                print(f"--- Página {i+1} ({len(texto)} caracteres) ---")
                print(texto[:800])
                print()

        if not texto_total.strip():
            print("⚠ El PDF no tiene texto extraíble.")
            print("  Posiblemente es una imagen escaneada.")
            print("  Se necesita OCR para leerlo.")
            sys.exit(0)

        print("=" * 60)
        print("  CAMPOS DETECTADOS")
        print("=" * 60)

        # Función para buscar valor después de una etiqueta
        def buscar(etiquetas, texto):
            lines = texto.split('\n')
            for i, line in enumerate(lines):
                for etiqueta in etiquetas:
                    if etiqueta.lower() in line.lower():
                        # Buscar en la misma línea después de ':'
                        partes = re.split(r':\s*', line, maxsplit=1)
                        if len(partes) > 1 and partes[1].strip():
                            val = partes[1].strip()
                            # Limpiar texto en inglés si viene en la misma línea
                            val = re.split(r'\s{2,}', val)[0]
                            if len(val) > 1:
                                return val
                        # Buscar en la línea siguiente
                        if i + 1 < len(lines):
                            sig = lines[i + 1].strip()
                            # Ignorar líneas que son etiquetas en inglés
                            if sig and not any(x in sig.lower() for x in ['name:', 'date:', 'number:', 'address:']):
                                return sig
            return None

        # Número de informe — buscar "No. LMD-" o "No. LM"
        numero = None
        patrones_num = [
            r'No\.\s+(LM[A-Z]-\d+-\d+)',
            r'No\.\s+([A-Z]{2,5}-\d+-\d+)',
            r'N[uú]mero\s+de\s+[Ii]nforme[:\s]+([A-Z0-9\-]+)',
        ]
        for p in patrones_num:
            m = re.search(p, texto_total)
            if m:
                numero = m.group(1)
                break

        # Año desde el número de informe (ej: LMD-143-25 → 2025)
        anio = None
        if numero:
            m_anio = re.search(r'-(\d{2})$', numero)
            if m_anio:
                anio = "20" + m_anio.group(1)

        campos = {
            "Número de informe":   numero,
            "Año (del informe)":   anio,
            "Nombre del cliente":  buscar(["Nombre del cliente", "Customer name"], texto_total),
            "Dirección":           buscar(["Dirección", "Address"], texto_total),
            "Atención a":          buscar(["Atención a", "Attention"], texto_total),
            "Descripción inst.":   buscar(["Descripción del instrumento", "Instrument description"], texto_total),
            "No. de serie":        buscar(["No. De Serie", "No. de serie", "Serial"], texto_total),
            "Identificación":      buscar(["Identificación No", "Identificacion"], texto_total),
            "Modelo":              buscar(["Modelo", "Model"], texto_total),
            "Marca":               buscar(["Marca", "Manufacturer"], texto_total),
            "Magnitud evaluada":   buscar(["Magnitud evaluada", "Evaluated quality"], texto_total),
            "Método utilizado":    buscar(["Método utilizado", "Used method"], texto_total),
            "Lugar calibración":   buscar(["Lugar de la calibración", "Place of calibration"], texto_total),
            "Fecha recepción":     buscar(["Fecha de recepción", "Reception date"], texto_total),
            "Fecha calibración":   buscar(["Fecha de calibración", "Date of calibration"], texto_total),
            "Fecha emisión":       buscar(["Fecha de emisión", "Date of issue"], texto_total),
        }

        encontrados = 0
        for campo, valor in campos.items():
            estado = "✅" if valor else "❌"
            if valor:
                encontrados += 1
            print(f"  {estado} {campo:<25} {valor or '— no encontrado'}")

        print(f"\n  Campos encontrados: {encontrados}/{len(campos)}")

        if encontrados >= 4:
            print("\n✅ RESULTADO: Este PDF SÍ puede importarse al sistema.")
        elif encontrados >= 2:
            print("\n⚠  RESULTADO: Importación parcial posible, algunos campos vacíos.")
        else:
            print("\n❌ RESULTADO: No se detectaron suficientes campos.")
            print("   El script necesita ajuste para este formato.")

except FileNotFoundError:
    print(f"❌ Archivo no encontrado: {RUTA_PDF}")
    print("   Verifica la ruta y vuelve a intentar.")
except Exception as e:
    print(f"❌ Error: {e}")
