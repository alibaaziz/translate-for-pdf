import os
import sys
import time
import fitz

from translator_engine import NllbTranslatorEngine
from pdf_processor import PdfProcessor

INPUT_PDF = r"C:\Users\a.amini\Desktop\partie 3.pdf"
OUTPUT_FR = r"C:\Users\a.amini\Desktop\partie 3_traduit_FR.pdf"
OUTPUT_AR = r"C:\Users\a.amini\Desktop\partie 3_traduit_AR.pdf"

def main():
    print("=== DEMARRAGE DE LA TRADUCTION COMPLETE DE 'partie 3.pdf' ===")
    t_start = time.time()

    print("[1/4] Initialisation du moteur Meta NLLB-200...")
    engine = NllbTranslatorEngine()
    print(f"      Peripherique actif : {engine.active_device_name} ({engine.compute_type})")

    # --- 1. Traduction vers le Francais ---
    print(f"\n[2/4] Traduction integrale vers le Francais -> {OUTPUT_FR}")
    t0 = time.time()
    def progress_fr(curr, total, msg):
        print(f"      [FR] Page {curr+1}/{total} : {msg}")

    success_fr = PdfProcessor.translate_document(
        input_pdf_path=INPUT_PDF,
        output_pdf_path=OUTPUT_FR,
        from_lang="en",
        to_lang="fr",
        translator_func=engine.translate_batch_texts,
        skip_figures=True,
        progress_callback=progress_fr
    )
    t1 = time.time()
    print(f"      -> Francais termine en {t1 - t0:.2f} secondes (Succes: {success_fr})")
    print(f"      Taille du fichier produit : {os.path.getsize(OUTPUT_FR) / 1024:.1f} Ko")

    # --- 2. Traduction vers l'Arabe ---
    print(f"\n[3/4] Traduction integrale vers l'Arabe -> {OUTPUT_AR}")
    t2 = time.time()
    def progress_ar(curr, total, msg):
        print(f"      [AR] Page {curr+1}/{total} : {msg}")

    success_ar = PdfProcessor.translate_document(
        input_pdf_path=INPUT_PDF,
        output_pdf_path=OUTPUT_AR,
        from_lang="en",
        to_lang="ar",
        translator_func=engine.translate_batch_texts,
        skip_figures=True,
        progress_callback=progress_ar
    )
    t3 = time.time()
    print(f"      -> Arabe termine en {t3 - t2:.2f} secondes (Succes: {success_ar})")
    print(f"      Taille du fichier produit : {os.path.getsize(OUTPUT_AR) / 1024:.1f} Ko")

    # --- 3. Rendu des pages d'inspection visuelle ---
    print("\n[4/4] Generation des apercus visuels pour verification...")
    pages_to_check = [1, 5, 6, 9, 11, 18] # pages 2, 6, 7, 10, 12, 19
    
    doc_fr = fitz.open(OUTPUT_FR)
    doc_ar = fitz.open(OUTPUT_AR)

    os.makedirs("inspection_output", exist_ok=True)

    for p in pages_to_check:
        p_num = p + 1
        pix_fr = doc_fr[p].get_pixmap(dpi=130)
        pix_fr.save(f"inspection_output/p{p_num}_FR.png")

        pix_ar = doc_ar[p].get_pixmap(dpi=130)
        pix_ar.save(f"inspection_output/p{p_num}_AR.png")
        print(f"      Page {p_num} rendue en FR et AR.")

    doc_fr.close()
    doc_ar.close()

    total_time = time.time() - t_start
    print(f"\n=== OPERATION TERMINEE EN {total_time:.2f} SECONDES ===")

if __name__ == "__main__":
    main()
