"""
scripts/diagnostico_pdf_v2.py
Prueba de extracción de texto de PDF con OCR (Tesseract)
Uso: python diagnostico_pdf_v2.py
"""
import sys, os
from pathlib import Path

# ⚠️ CAMBIA ESTA RUTA por la de tu PDF de prueba
RUTA_PDF = r"C:\PruebaLocal\LMD-065-15.pdf"

print("=" * 60)
print("🔍 Diagnóstico de extracción de texto PDF (incluye OCR)")
print(f"Archivo: {RUTA_PDF}")
print()

# 1. pdfplumber
print("1. Probando pdfplumber...")
try:
    import pdfplumber
    with pdfplumber.open(RUTA_PDF) as pdf:
        print(f"   Páginas: {len(pdf.pages)}")
        for i, page in enumerate(pdf.pages[:2]):
            texto = page.extract_text()
            if texto:
                print(f"   Página {i+1} texto ({len(texto)} chars):")
                print(texto[:300])
            else:
                print(f"   Página {i+1}: SIN TEXTO")
except Exception as e:
    print(f"   ❌ ERROR pdfplumber: {e}")

print()

# 2. pymupdf (fitz)
print("2. Probando pymupdf (fitz)...")
try:
    import fitz
    doc = fitz.open(RUTA_PDF)
    print(f"   Páginas: {doc.page_count}")
    for i in range(min(2, doc.page_count)):
        pagina = doc[i]
        texto = pagina.get_text()
        if texto.strip():
            print(f"   Página {i+1} texto ({len(texto)} chars):")
            print(texto[:300])
        else:
            print(f"   Página {i+1}: SIN TEXTO")
    doc.close()
except Exception as e:
    print(f"   ❌ ERROR pymupdf: {e}")

print()

# 3. OCR con Tesseract
print("3. Probando OCR con Tesseract (primera página)...")
try:
    import pytesseract
    from PIL import Image
    import fitz

    # Si Tesseract no está en el PATH, descomenta y ajusta la ruta:
    # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    # Verificar que Tesseract está accesible
    print(f"   Tesseract version: {pytesseract.get_tesseract_version()}")

    doc = fitz.open(RUTA_PDF)
    pagina = doc[0]  # primera página
    # Renderizar a imagen (DPI alto para mejor OCR)
    pix = pagina.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    # Aplicar OCR con español + inglés
    texto_ocr = pytesseract.image_to_string(img, lang='spa+eng')
    doc.close()
    
    if texto_ocr.strip():
        print(f"   ✅ OCR exitoso ({len(texto_ocr)} chars):")
        print(texto_ocr[:500])  # primeras 500 caracteres
        print()
        # Buscar etiquetas comunes para ver si extrajo bien los datos
        etiquetas = ['Nombre del cliente', 'Customer name', 'Fecha de emisión', 'No. de serie',
                     'Marca', 'Modelo', 'Magnitud']
        print("   Búsqueda de etiquetas comunes:")
        for eti in etiquetas:
            if eti.lower() in texto_ocr.lower():
                print(f"     ✅ '{eti}' encontrada")
            else:
                print(f"     ❌ '{eti}' NO encontrada")
    else:
        print("   ❌ OCR no devolvió texto (imagen ilegible o sin contenido)")
except ImportError as e:
    print(f"   ❌ Falta librería: {e}")
    print("   Instala con: pip install pytesseract Pillow pymupdf")
except Exception as e:
    print(f"   ❌ Error en OCR: {e}")

print()
print("=" * 60)
print("✅ Diagnóstico completado")
print("=" * 60)