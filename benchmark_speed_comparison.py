import time
import os
import fitz
from translator_engine import NllbTranslatorEngine
from pdf_processor import PdfProcessor

INPUT_PDF = r"C:\Users\a.amini\Desktop\partie 3.pdf"

def main():
    print("=================================================================")
    print("    BENCHMARK COMPARATIF REEL SUR 'partie 3.pdf' (NVIDIA GPU)    ")
    print("=================================================================\n")

    engine = NllbTranslatorEngine()
    engine._load_model()
    print(f"[Configuration] Moteur : {engine.active_device_name} ({engine.compute_type})")
    print(f"[Document] Source : {INPUT_PDF}")

    doc = fitz.open(INPUT_PDF)
    total_pages = len(doc)
    print(f"[Document] Nombre total de pages : {total_pages}\n")

    # Selection de 5 pages representatives de complexite variee :
    # Page 2 : standard avec photos et texte
    # Page 6 : diagrammes et sous-sections
    # Page 7 : tres complexe (tableau NATM, 2800 vecteurs)
    # Page 8 : tres dense en texte (44 lignes)
    # Page 11 : texte technique dense
    sample_pages = [1, 5, 6, 7, 10] # 0-indexed -> pages 2, 6, 7, 8, 11

    results = []

    for p_idx in sample_pages:
        p_num = p_idx + 1
        # Isoler la page dans un PDF temporaire
        single_doc = fitz.open()
        single_doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx)
        tmp_in = f"tmp_bench_p{p_num}.pdf"
        tmp_out_seq = f"tmp_out_seq_p{p_num}.pdf"
        tmp_out_batch = f"tmp_out_batch_p{p_num}.pdf"
        single_doc.save(tmp_in)
        single_doc.close()

        # -------------------------------------------------------------
        # TEST 1 : Mode Séquentiel (ancien mode bloc par bloc)
        # -------------------------------------------------------------
        engine._translation_cache.clear()
        t0 = time.time()
        # Fonction sequentielle pure sans batch
        def seq_translate(text, fl, tl):
            return engine.translate_text(text, fl, tl)
        
        # Forcer le mode sequentiel en masquant translate_batch_texts
        PdfProcessor.translate_document(
            tmp_in, tmp_out_seq, "en", "fr",
            translator_func=seq_translate
        )
        t_seq = time.time() - t0

        # -------------------------------------------------------------
        # TEST 2 : Mode Batch GPU (nouveau mode parallèle par page)
        # -------------------------------------------------------------
        engine._translation_cache.clear()
        t1 = time.time()
        PdfProcessor.translate_document(
            tmp_in, tmp_out_batch, "en", "fr",
            translator_func=engine.translate_batch_texts
        )
        t_batch = time.time() - t1

        speedup = t_seq / t_batch if t_batch > 0 else 1.0
        time_saved = t_seq - t_batch
        pct_saved = (time_saved / t_seq) * 100 if t_seq > 0 else 0.0

        results.append({
            "page": p_num,
            "t_seq": t_seq,
            "t_batch": t_batch,
            "speedup": speedup,
            "saved": time_saved,
            "pct": pct_saved
        })

        print(f"-> Page {p_num:2d} : Séquentiel = {t_seq:5.2f}s | Batch GPU = {t_batch:5.2f}s | Accélération = {speedup:4.1f}x ({pct_saved:4.1f}% de temps gagné)")

        # Nettoyage fichiers temporaires
        for f in [tmp_in, tmp_out_seq, tmp_out_batch]:
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass

    # Recapitulatif global
    total_seq = sum(r["t_seq"] for r in results)
    total_batch = sum(r["t_batch"] for r in results)
    overall_speedup = total_seq / total_batch if total_batch > 0 else 1.0

    print("\n" + "="*65)
    print("                    TABLEAU RÉCAPITULATIF                    ")
    print("="*65)
    print(f"{'Page':<8}{'Séquentiel (s)':<18}{'Batch GPU (s)':<18}{'Gain / Facteur':<15}")
    print("-" * 65)
    for r in results:
        print(f"Page {r['page']:<4}{r['t_seq']:<18.2f}{r['t_batch']:<18.2f}{r['speedup']:.1f}x plus rapide (-{r['pct']:.0f}%)")
    print("-" * 65)
    print(f"{'TOTAL':<8}{total_seq:<18.2f}{total_batch:<18.2f}{overall_speedup:.1f}x plus rapide (-{(total_seq-total_batch)/total_seq*100:.0f}%)")
    print("="*65)

if __name__ == "__main__":
    main()
