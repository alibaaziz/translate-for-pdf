import os
import io
import fitz
from PIL import Image
from pdf_processor import PdfProcessor
from translator_engine import NllbTranslatorEngine


def create_sample_pdf(pdf_path: str):
    """
    Creates a sample PDF with vector graphics, embedded images,
    colored text blocks, and multiple paragraphs.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 size

    # 1. Vector graphics : Colored background banner and table border
    page.draw_rect(fitz.Rect(30, 30, 565, 90), color=(0.1, 0.3, 0.7), fill=(0.92, 0.95, 1.0), width=1.5)
    page.draw_rect(fitz.Rect(30, 110, 565, 400), color=(0.8, 0.8, 0.8), fill=(0.98, 0.98, 0.98), width=1)
    page.draw_line(fitz.Point(30, 150), fitz.Point(565, 150), color=(0.7, 0.7, 0.7), width=1)

    # 2. Embedded raster image (colorful test square)
    img = Image.new("RGB", (120, 120), color=(34, 197, 94))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(fitz.Rect(400, 170, 520, 290), stream=buf.getvalue())

    # 3. Text blocks
    # Header inside banner
    page.insert_textbox(
        fitz.Rect(45, 40, 550, 80),
        "Document Translation and Layout Preservation System",
        fontsize=16,
        color=(0.1, 0.2, 0.6)
    )

    # Subtitle
    page.insert_textbox(
        fitz.Rect(45, 120, 380, 145),
        "Section 1: Automated Offline Neural Translation",
        fontsize=13,
        color=(0.15, 0.15, 0.15)
    )

    # Paragraph text
    body_text = (
        "This document contains important technical information. "
        "The translation engine replaces text within the original bounding box "
        "without modifying images, vector lines, or background formatting. "
        "All visual elements remain in their original positions."
    )
    page.insert_textbox(
        fitz.Rect(45, 165, 370, 320),
        body_text,
        fontsize=10.5,
        color=(0.2, 0.2, 0.2)
    )

    doc.save(pdf_path)
    doc.close()
    print(f"Sample PDF created: {pdf_path}")


def test_full_pipeline():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    sample_pdf = os.path.join(test_dir, "sample_test.pdf")
    translated_pdf = os.path.join(test_dir, "translated_test.pdf")

    print("\n--- Étape 1 : Création du PDF source avec images et tracés vectoriels ---")
    create_sample_pdf(sample_pdf)

    # Verify source counts
    src_doc = fitz.open(sample_pdf)
    src_page = src_doc[0]
    src_images_count = len(src_page.get_images())
    src_drawings_count = len(src_page.get_drawings())
    src_text = src_page.get_text()
    src_doc.close()

    print(f"PDF Source -> Images: {src_images_count}, Tracés vectoriels: {src_drawings_count}")
    assert src_images_count == 1, "Le PDF source doit contenir 1 image"
    assert src_drawings_count >= 2, "Le PDF source doit contenir des graphiques vectoriels"

    print("\n--- Étape 2 : Traduction hors-ligne et préservation de la mise en page ---")
    engine = NllbTranslatorEngine()

    # Test detection
    detected = engine.detect_language(src_text)
    print(f"Langue détectée automatiquement : {detected}")
    assert detected == "en", f"La langue détectée devrait être 'en', reçu: {detected}"

    # Perform translation
    success = PdfProcessor.translate_document(
        input_pdf_path=sample_pdf,
        output_pdf_path=translated_pdf,
        from_lang="en",
        to_lang="fr",
        translator_func=engine.translate_text,
        progress_callback=lambda cur, total, msg: print(f"[{cur}/{total}] {msg}")
    )
    assert success, "La traduction a échoué !"

    print("\n--- Étape 3 : Vérification de la conservation absolue ---")
    res_doc = fitz.open(translated_pdf)
    res_page = res_doc[0]
    res_images_count = len(res_page.get_images())
    res_drawings_count = len(res_page.get_drawings())
    res_text = res_page.get_text()
    res_doc.close()

    print(f"PDF Traduit -> Images: {res_images_count}, Tracés vectoriels: {res_drawings_count}")
    print(f"Extrait du texte traduit:\n{res_text.strip()}")

    # Critical assertions
    assert res_images_count == src_images_count, (
        f"Images perdues ! Source: {src_images_count}, Traduit: {res_images_count}"
    )
    assert res_drawings_count == src_drawings_count, (
        f"Graphiques perdus ! Source: {src_drawings_count}, Traduit: {res_drawings_count}"
    )

    print("\n[SUCCES] TEST REUSSI : 100% des images et des graphiques ont ete conserves !")


if __name__ == "__main__":
    test_full_pipeline()
