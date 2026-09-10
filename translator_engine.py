import os
import sys
import re
import site
import langdetect


def setup_cuda_dlls():
    """Ensure Windows locates cublas64_12.dll and cudnn DLLs for NVIDIA GPU acceleration."""
    if sys.platform != "win32":
        return
    search_dirs = []
    # 1. CUDA toolkit environment variables
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path and os.path.isdir(cuda_path):
        search_dirs.append(os.path.join(cuda_path, "bin"))
    
    # 2. Frozen PyInstaller directories
    if getattr(sys, "frozen", False):
        app_root = os.path.dirname(sys.executable)
        search_dirs.extend([
            app_root,
            os.path.join(app_root, "_internal"),
            os.path.join(app_root, "_internal", "ctranslate2"),
            os.path.join(app_root, "_internal", "nvidia", "cublas", "bin"),
            os.path.join(app_root, "_internal", "nvidia", "cudnn", "bin"),
            os.path.join(app_root, "_internal", "torch", "lib"),
        ])
    
    # 3. Python site-packages (for standard run.bat / python execution)
    try:
        for sp in site.getsitepackages():
            search_dirs.extend([
                os.path.join(sp, "nvidia", "cublas", "bin"),
                os.path.join(sp, "nvidia", "cudnn", "bin"),
                os.path.join(sp, "torch", "lib"),
                os.path.join(sp, "ctranslate2"),
            ])
    except Exception:
        pass

    # 4. Standard local CUDA paths
    for v in ["v12.6", "v12.5", "v12.4", "v12.3", "v12.2", "v12.1", "v12.0"]:
        p = f"C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\{v}\\bin"
        if os.path.isdir(p):
            search_dirs.append(p)

    for d in search_dirs:
        if os.path.isdir(d):
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
            os.environ["PATH"] = d + ";" + os.environ.get("PATH", "")


import json
import httpx

try:
    setup_cuda_dlls()
    import ctranslate2
    from transformers import AutoTokenizer
    CTRANSLATE2_AVAILABLE = True
except Exception:
    ctranslate2 = None
    AutoTokenizer = None
    CTRANSLATE2_AVAILABLE = False

from config import (
    SUPPORTED_LANGUAGES, LANGUAGE_NAME_TO_CODE, LANGUAGE_CODE_TO_NAME,
    ISO_TO_NLLB, NLLB_LOCAL_DIR, NLLB_MODEL_REPO
)


class NllbTranslatorEngine:
    """
    Hybrid Translation Engine:
    - Primary: High-speed Cloud LPU inference via Groq (Llama 3.3 70B & 3.1 8B)
      -> 0 Mo RAM overhead, 500+ tokens/sec, near-instant translation
    - Fallback: Offline Meta NLLB-200 via CTranslate2 (GPU/CPU)
    """
    def __init__(self):
        self.model_dir = NLLB_LOCAL_DIR
        self.translator = None
        self.tokenizer = None
        self._translation_cache = {}
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

        cuda_count = 0
        if CTRANSLATE2_AVAILABLE:
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:
                cuda_count = 0
        self.device = "cuda" if cuda_count > 0 else "cpu"
        self.compute_type = "int8_float16" if self.device == "cuda" else "int8"
        if self.groq_api_key:
            self.active_device_name = f"Groq LPU Cloud ({self.groq_model})"
        else:
            self.active_device_name = "NVIDIA CUDA (GPU)" if self.device == "cuda" else "Processeur (CPU)"

    def detect_language(self, text: str) -> str:
        """
        Detect language of the document using langdetect.
        Returns 2-letter ISO 639-1 code (e.g. 'en', 'fr', 'es').
        """
        if not text or not text.strip():
            return "en"
        cleaned = re.sub(r"[0-9\W_]+", " ", text).strip()
        if len(cleaned) < 5:
            return "en"
        try:
            detected = langdetect.detect(cleaned)
            if detected in LANGUAGE_CODE_TO_NAME:
                return detected
            if detected.startswith("zh"):
                return "zh"
            return detected
        except Exception:
            return "en"

    def is_package_installed(self, from_code: str = None, to_code: str = None) -> bool:
        """
        In NLLB-200, a single universal model covers all 200 languages.
        """
        bin_file = os.path.join(self.model_dir, "model.bin")
        sp_file = os.path.join(self.model_dir, "sentencepiece.bpe.model")
        return os.path.exists(bin_file) and os.path.exists(sp_file)

    def get_installed_language_codes(self) -> set:
        """
        Returns all languages supported once NLLB-200 is installed.
        """
        if self.is_package_installed():
            return set(ISO_TO_NLLB.keys())
        return set()

    def install_language_pair(self, from_code: str = None, to_code: str = None, progress_callback=None) -> bool:
        """
        Downloads and sets up the universal Meta NLLB-200 model once.
        """
        from huggingface_hub import snapshot_download
        if progress_callback:
            progress_callback("Téléchargement du modèle universel Meta NLLB-200 (~600 Mo, 200 langues)...")
        os.makedirs(self.model_dir, exist_ok=True)
        snapshot_download(
            repo_id=NLLB_MODEL_REPO,
            local_dir=self.model_dir
        )
        if progress_callback:
            progress_callback("Modèle Meta NLLB-200 prêt !")
        return True

    def _load_model(self):
        """
        Lazy-loads the CTranslate2 model and tokenizer into memory.
        Tests CUDA compatibility and falls back seamlessly to CPU (int8).
        """
        if self.translator is None:
            if not self.is_package_installed():
                self.install_language_pair()
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_dir,
                clean_up_tokenization_spaces=False
            )
            
            # Attempt CUDA if available, but probe execution to handle missing DLLs
            if self.device == "cuda":
                try:
                    probe_trans = ctranslate2.Translator(
                        self.model_dir,
                        device="cuda",
                        compute_type=self.compute_type
                    )
                    # Test probe inference
                    probe_trans.translate_batch([[" </s>"]], max_decoding_length=1)
                    self.translator = probe_trans
                except Exception as e:
                    print(f"[NLLB-200] CUDA non opérationnel ({e}). Bascule automatique sur CPU (int8)...")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self.translator = ctranslate2.Translator(
                        self.model_dir,
                        device="cpu",
                        compute_type="int8"
                    )
            else:
                self.translator = ctranslate2.Translator(
                    self.model_dir,
                    device="cpu",
                    compute_type="int8"
                )

    def _translate_batch_groq(self, texts_to_translate: list, from_code: str, to_code: str) -> list:
        """
        Translates a list of texts using Groq Cloud API (Llama 3.3 70B / 3.1 8B).
        Ultra-low latency (~0.3s), zero RAM overhead, SOTA translation quality.
        """
        api_key = os.environ.get("GROQ_API_KEY", self.groq_api_key).strip()
        if not api_key or not texts_to_translate:
            print("[Groq API] Clé GROQ_API_KEY absente ou liste vide.")
            return None

        src_name = LANGUAGE_CODE_TO_NAME.get(from_code, from_code)
        tgt_name = LANGUAGE_CODE_TO_NAME.get(to_code, to_code)
        model = os.environ.get("GROQ_MODEL", self.groq_model or "llama-3.3-70b-versatile").strip()

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        chunk_size = 15
        all_translated = []

        for i in range(0, len(texts_to_translate), chunk_size):
            chunk = texts_to_translate[i:i + chunk_size]
            prompt_instruction = (
                f"You are a professional document translation engine. "
                f"Translate each text item in the provided JSON array from {src_name} ({from_code}) to {tgt_name} ({to_code}).\n"
                f"Rules:\n"
                f"1. Output a JSON object with key 'translations': [\"item1\", \"item2\", ...]\n"
                f"2. The array 'translations' must contain EXACTLY {len(chunk)} translated strings corresponding 1:1 to the input items.\n"
                f"3. Preserve all numbers, acronyms, placeholders, and formatting.\n"
                f"4. Do NOT output explanations or notes. ONLY valid JSON."
            )

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt_instruction},
                    {"role": "user", "content": json.dumps({"texts": chunk}, ensure_ascii=False)}
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }

            success = False
            for try_model in [model, "llama-3.1-8b-instant"]:
                payload["model"] = try_model
                try:
                    with httpx.Client(timeout=45.0) as client:
                        resp = client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            raw_content = data["choices"][0]["message"]["content"].strip()
                            if "```" in raw_content:
                                raw_content = re.sub(r"^```(?:json)?\s*", "", raw_content, flags=re.MULTILINE)
                                raw_content = re.sub(r"\s*```$", "", raw_content, flags=re.MULTILINE)
                            start_brace = raw_content.find("{")
                            end_brace = raw_content.rfind("}")
                            if start_brace != -1 and end_brace != -1:
                                raw_content = raw_content[start_brace:end_brace + 1]

                            parsed = json.loads(raw_content)
                            translations = None
                            if isinstance(parsed, dict):
                                translations = parsed.get("translations") or parsed.get("translated_texts") or list(parsed.values())[0]
                            elif isinstance(parsed, list):
                                translations = parsed

                            if isinstance(translations, list) and len(translations) == len(chunk):
                                all_translated.extend(translations)
                                success = True
                                break
                            else:
                                print(f"[Groq API] Mismatch length on {try_model}: got {len(translations) if isinstance(translations, list) else 'non-list'}, expected {len(chunk)}")
                        else:
                            print(f"[Groq API] HTTP {resp.status_code} on {try_model}: {resp.text[:300]}")
                except Exception as e:
                    print(f"[Groq API] Error on {try_model}: {e}")

            if not success:
                print(f"[Groq API] Translation failed for chunk of {len(chunk)} elements.")
                all_translated.extend(chunk)

        return all_translated

    def translate_text(self, text: str, from_code: str, to_code: str) -> str:
        """
        Translates text using Groq Cloud API or offline Meta NLLB-200.
        """
        if not text or not text.strip() or from_code == to_code:
            return text

        # Clean up broken characters in input
        cleaned_text = text.replace('\ufffd', ' - ').replace('\u2002', ' ').replace('\u2009', ' ')
        cleaned_text = re.sub(r'\s*-\s*', ' - ', cleaned_text).strip()

        # Guard: never translate figure/table/photo labels into hallucinations
        if re.match(r'^(?:Fig(?:ure)?|Photo|Tab(?:le)?|Graph(?:ique)?|Diagram(?:me)?|Chart|Schema|Planche)\b', cleaned_text, re.IGNORECASE):
            return cleaned_text

        cache_key = (cleaned_text, from_code, to_code)
        if cache_key in self._translation_cache:
            return self._translation_cache[cache_key]

        groq_key = os.environ.get("GROQ_API_KEY", self.groq_api_key).strip()
        if groq_key:
            res = self.translate_batch_texts([cleaned_text], from_code, to_code)
            if res and len(res) > 0:
                return res[0]

        try:
            self._load_model()
            src_nllb = ISO_TO_NLLB.get(from_code, "eng_Latn")
            tgt_nllb = ISO_TO_NLLB.get(to_code, "fra_Latn")

            self.tokenizer.src_lang = src_nllb
            target_prefix = [tgt_nllb]

            raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned_text) if s.strip()]
            if len(raw_sentences) <= 1:
                source_tokens = self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(cleaned_text))
                results = self.translator.translate_batch([source_tokens], target_prefix=[target_prefix], max_decoding_length=256)
                target_tokens = results[0].hypotheses[0][1:]
                translated = self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(target_tokens))
            else:
                tokens_list = [self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(s)) for s in raw_sentences]
                prefixes = [target_prefix] * len(tokens_list)
                results = self.translator.translate_batch(tokens_list, target_prefix=prefixes, max_decoding_length=256)
                trans_parts = []
                for res in results:
                    tgt_toks = res.hypotheses[0][1:]
                    trans_parts.append(self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(tgt_toks)))
                translated = " ".join(trans_parts)

            translated = translated.replace('<unk>', '-').replace('< unk >', '-').replace(' - - ', ' - ').strip()

            lower_trans = translated.lower()
            if any(h in lower_trans for h in ["je sais pas", "je ne sais pas", "je suis un peu triste", "i don't know", "i do not know", "sais pas", "un peu triste"]):
                if len(cleaned_text.split()) <= 6 or re.match(r'^(?:Fig|Photo|Tab|Graph|Diagram)\b', cleaned_text, re.IGNORECASE):
                    translated = cleaned_text

            self._translation_cache[cache_key] = translated
            return translated
        except Exception as e:
            print(f"Erreur NLLB-200: {e}")
            return text

    def translate_batch_texts(self, texts: list, from_code: str, to_code: str, beam_size: int = 1) -> list:
        """
        Translates a list of texts in batch:
        - Checks in-memory cache
        - Prioritizes high-speed Groq LPU API if GROQ_API_KEY is configured
        - Falls back gracefully to Meta NLLB-200 local engine
        """
        if not texts or from_code == to_code:
            return list(texts)

        results_by_index = [None] * len(texts)
        texts_to_translate_indices = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                results_by_index[idx] = text
                continue

            cleaned_text = text.replace('\ufffd', ' - ').replace('\u2002', ' ').replace('\u2009', ' ')
            cleaned_text = re.sub(r'\s*-\s*', ' - ', cleaned_text).strip()

            if re.match(r'^(?:Fig(?:ure)?|Photo|Tab(?:le)?|Graph(?:ique)?|Diagram(?:me)?|Chart|Schema|Planche)\b', cleaned_text, re.IGNORECASE):
                results_by_index[idx] = cleaned_text
                continue

            cache_key = (cleaned_text, from_code, to_code)
            if cache_key in self._translation_cache:
                results_by_index[idx] = self._translation_cache[cache_key]
                continue

            texts_to_translate_indices.append((idx, cleaned_text))

        # 1. Attempt Groq Cloud Translation
        groq_key = os.environ.get("GROQ_API_KEY", self.groq_api_key).strip()
        if groq_key and texts_to_translate_indices:
            try:
                raw_chunk = [item[1] for item in texts_to_translate_indices]
                groq_translated = self._translate_batch_groq(raw_chunk, from_code, to_code)
                if groq_translated and len(groq_translated) == len(texts_to_translate_indices):
                    for (t_idx, orig_text), trans in zip(texts_to_translate_indices, groq_translated):
                        results_by_index[t_idx] = trans
                        self._translation_cache[(orig_text, from_code, to_code)] = trans
                    for idx in range(len(texts)):
                        if results_by_index[idx] is None:
                            results_by_index[idx] = texts[idx]
                    return results_by_index
            except Exception as e:
                print(f"[Groq Cloud Engine] Exception: {e}, falling back to local NLLB")

        # 2. Fallback to local Meta NLLB-200 if CTranslate2 is available
        if not CTRANSLATE2_AVAILABLE:
            for t_idx, orig_text in texts_to_translate_indices:
                results_by_index[t_idx] = orig_text
            for idx in range(len(texts)):
                if results_by_index[idx] is None:
                    results_by_index[idx] = texts[idx]
            return results_by_index

        self._load_model()
        src_nllb = ISO_TO_NLLB.get(from_code, "eng_Latn")
        tgt_nllb = ISO_TO_NLLB.get(to_code, "fra_Latn")
        self.tokenizer.src_lang = src_nllb
        target_prefix = [tgt_nllb]

        results_by_index = [None] * len(texts)
        texts_to_translate_indices = []
        flat_sentences = []
        sentence_to_text_idx = []

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                results_by_index[idx] = text
                continue

            cleaned_text = text.replace('\ufffd', ' - ').replace('\u2002', ' ').replace('\u2009', ' ')
            cleaned_text = re.sub(r'\s*-\s*', ' - ', cleaned_text).strip()

            # Guard: preserve figure/table/photo captions intact
            if re.match(r'^(?:Fig(?:ure)?|Photo|Tab(?:le)?|Graph(?:ique)?|Diagram(?:me)?|Chart|Schema|Planche)\b', cleaned_text, re.IGNORECASE):
                results_by_index[idx] = cleaned_text
                continue

            cache_key = (cleaned_text, from_code, to_code)
            if cache_key in self._translation_cache:
                results_by_index[idx] = self._translation_cache[cache_key]
                continue

            texts_to_translate_indices.append((idx, cleaned_text))
            raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned_text) if s.strip()]
            if not raw_sentences:
                raw_sentences = [cleaned_text]

            for s in raw_sentences:
                flat_sentences.append(s)
                sentence_to_text_idx.append(idx)

        if flat_sentences:
            try:
                tokens_list = [self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(s)) for s in flat_sentences]
                prefixes = [target_prefix] * len(tokens_list)
                raw_batch_results = self.translator.translate_batch(
                    tokens_list,
                    target_prefix=prefixes,
                    max_decoding_length=256,
                    beam_size=beam_size
                )

                decoded_by_text_idx = {t_idx: [] for t_idx, _ in texts_to_translate_indices}
                for i, r in enumerate(raw_batch_results):
                    tgt_toks = r.hypotheses[0][1:]
                    dec = self.tokenizer.decode(self.tokenizer.convert_tokens_to_ids(tgt_toks))
                    dec = dec.replace('<unk>', '-').replace('< unk >', '-').replace(' - - ', ' - ').strip()
                    orig_idx = sentence_to_text_idx[i]
                    decoded_by_text_idx[orig_idx].append(dec)

                for t_idx, cleaned_text in texts_to_translate_indices:
                    translated_joined = " ".join(decoded_by_text_idx[t_idx]).strip()
                    # Guard against conversational hallucinations on short technical text
                    lower_join = translated_joined.lower()
                    if any(h in lower_join for h in ["je sais pas", "je ne sais pas", "je suis un peu triste", "i don't know", "i do not know", "sais pas", "un peu triste"]):
                        if len(cleaned_text.split()) <= 6 or re.match(r'^(?:Fig|Photo|Tab|Graph|Diagram)\b', cleaned_text, re.IGNORECASE):
                            translated_joined = cleaned_text
                    results_by_index[t_idx] = translated_joined
                    self._translation_cache[(cleaned_text, from_code, to_code)] = translated_joined
            except Exception as e:
                print(f"Erreur batch NLLB-200: {e}")
                for t_idx, cleaned_text in texts_to_translate_indices:
                    results_by_index[t_idx] = cleaned_text

        for idx in range(len(texts)):
            if results_by_index[idx] is None:
                results_by_index[idx] = texts[idx]

        return results_by_index
