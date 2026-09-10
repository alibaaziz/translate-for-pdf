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
import time
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
        self._model_rotation_idx = 0
        self._model_cooldowns = {}

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

    def _get_groq_chat_models(self, api_key: str) -> list:
        cached = getattr(self, "_cached_groq_chat_models", None)
        if cached:
            return cached

        def is_valid_chat_model(m_id: str) -> bool:
            low = m_id.lower()
            if any(bad in low for bad in ["whisper", "guard", "safeguard", "audio", "orpheus", "vision", "embed"]):
                return False
            return True

        preferred = [
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.6-27b",
            "allam-2-7b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "llama3-8b-8192"
        ]

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {api_key}"})
                if resp.status_code == 200:
                    available = [m["id"] for m in resp.json().get("data", [])]
                    chat_models = [m for m in available if is_valid_chat_model(m)]

                    ordered = []
                    for pref in preferred:
                        for cand in chat_models:
                            if pref.lower() in cand.lower() and cand not in ordered:
                                ordered.append(cand)
                    for cand in chat_models:
                        if cand not in ordered:
                            ordered.append(cand)

                    if ordered:
                        print(f"[Groq Engine] Modeles de chat valides: {ordered}")
                        self._cached_groq_chat_models = ordered
                        return ordered
        except Exception as e:
            print(f"[Groq Engine] Erreur detection des modeles: {e}")

        self._cached_groq_chat_models = ["qwen/qwen3.8-27b"]
        return self._cached_groq_chat_models

    def _get_best_groq_model(self, api_key: str) -> str:
        models = self._get_groq_chat_models(api_key)
        return models[0] if models else "qwen/qwen3.8-27b"

    def _parse_translations_from_response(self, raw_content: str, expected_count: int, fallback_chunk: list) -> list:
        if not raw_content or not raw_content.strip():
            return fallback_chunk

        clean = raw_content.strip()
        if "```" in clean:
            clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.MULTILINE)
            clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
            clean = clean.strip()

        candidate_list = None

        # 1. Standard JSON parse
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, list) and len(parsed) > 0:
                candidate_list = [str(x) for x in parsed]
            elif isinstance(parsed, dict):
                for key in ["translations", "translated_texts", "texts", "result", "items"]:
                    val = parsed.get(key)
                    if isinstance(val, list) and len(val) > 0:
                        candidate_list = [str(x) for x in val]
                        break
                if not candidate_list:
                    for val in parsed.values():
                        if isinstance(val, list) and len(val) > 0:
                            candidate_list = [str(x) for x in val]
                            break
        except Exception:
            pass

        # 2. Extract JSON array substring [ ... ]
        if not candidate_list:
            start_bracket = clean.find("[")
            end_bracket = clean.rfind("]")
            if start_bracket != -1 and end_bracket > start_bracket:
                try:
                    sub_arr = json.loads(clean[start_bracket:end_bracket + 1])
                    if isinstance(sub_arr, list) and len(sub_arr) > 0:
                        candidate_list = [str(x) for x in sub_arr]
                except Exception:
                    pass

        # 3. Extract JSON object substring { ... }
        if not candidate_list:
            start_brace = clean.find("{")
            end_brace = clean.rfind("}")
            if start_brace != -1 and end_brace > start_brace:
                try:
                    sub_obj = json.loads(clean[start_brace:end_brace + 1])
                    if isinstance(sub_obj, dict):
                        for val in sub_obj.values():
                            if isinstance(val, list) and len(val) > 0:
                                candidate_list = [str(x) for x in val]
                                break
                except Exception:
                    pass

        # 4. If we have a candidate list, adjust length to expected_count
        if candidate_list:
            if len(candidate_list) >= expected_count:
                return candidate_list[:expected_count]
            padded = list(candidate_list)
            for i in range(len(candidate_list), expected_count):
                padded.append(fallback_chunk[i])
            return padded

        # 5. Line-by-line fallback
        lines = [re.sub(r"^\s*(?:\d+[\.\)]|[-*•])\s*", "", line).strip() for line in clean.splitlines() if line.strip()]
        lines = [re.sub(r'^[\[\{\"\'\s]+|[\]\}\"\'\s,]+$', '', l).strip() for l in lines if l.strip()]
        if len(lines) >= expected_count:
            return lines[:expected_count]
        elif len(lines) > 0:
            padded = list(lines)
            for i in range(len(lines), expected_count):
                padded.append(fallback_chunk[i])
            return padded

        return fallback_chunk

    def _pick_next_groq_model(self, chat_models: list) -> tuple[str, float]:
        """
        Picks the next available model in round-robin fashion, skipping any model
        currently in cooldown due to a 429 rate limit. If all models are in cooldown,
        returns the model whose cooldown expires earliest and the seconds to wait.
        """
        now = time.time()
        available = [m for m in chat_models if now >= self._model_cooldowns.get(m, 0.0)]
        if available:
            idx = self._model_rotation_idx % len(available)
            self._model_rotation_idx += 1
            return available[idx], 0.0

        # All models currently in cooldown: find the earliest expiring cooldown
        earliest_m = min(chat_models, key=lambda m: self._model_cooldowns.get(m, 0.0))
        wait_time = max(0.2, self._model_cooldowns.get(earliest_m, now) - now + 0.2)
        return earliest_m, wait_time

    def _translate_batch_groq(self, texts_to_translate: list, from_code: str, to_code: str) -> list:
        """
        Translates a list of texts using Groq Cloud API.
        Features:
        - Whole-page chunks (~12 items) to minimize HTTP round-trips
        - Round-robin model rotation across calls (Qwen, GPT-OSS, Allam)
        - Cooldown tracking on HTTP 429 so traffic routes instantly to healthy models
        - Adaptive parser that never drops translated segments
        """
        api_key = os.environ.get("GROQ_API_KEY", self.groq_api_key).strip()
        if not api_key or not texts_to_translate:
            print("[Groq API] Clé GROQ_API_KEY absente ou liste vide.")
            return None

        src_name = LANGUAGE_CODE_TO_NAME.get(from_code, from_code)
        tgt_name = LANGUAGE_CODE_TO_NAME.get(to_code, to_code)
        chat_models = self._get_groq_chat_models(api_key)
        if not chat_models:
            chat_models = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "allam-2-7b"]

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        chunk_size = 12
        all_translated = []

        for i in range(0, len(texts_to_translate), chunk_size):
            chunk = texts_to_translate[i:i + chunk_size]
            prompt_instruction = (
                f"You are a professional document translation engine. "
                f"Translate each text item in the provided JSON array from {src_name} ({from_code}) to {tgt_name} ({to_code}).\n"
                f"Strict Rules:\n"
                f"1. Output ONLY a valid JSON object with key 'translations': [\"item1\", \"item2\", ...]\n"
                f"2. The array 'translations' must contain EXACTLY {len(chunk)} translated strings corresponding 1:1 to the input items.\n"
                f"3. Preserve all numbers, acronyms, placeholders, and formatting.\n"
                f"4. Do NOT output any explanations, markdown notes, or commentary. ONLY the JSON object."
            )

            success = False
            max_attempts = 10

            for attempt in range(max_attempts):
                try_model, wait_needed = self._pick_next_groq_model(chat_models)
                if wait_needed > 0.0:
                    wait_secs = min(wait_needed, 6.0)
                    print(f"[Groq Engine] Tous les modèles sont en attente de quota. Pause de {wait_secs:.1f}s pour {try_model}...")
                    time.sleep(wait_secs)

                payload = {
                    "model": try_model,
                    "messages": [
                        {"role": "system", "content": prompt_instruction},
                        {"role": "user", "content": json.dumps({"texts": chunk}, ensure_ascii=False)}
                    ],
                    "temperature": 0.1
                }

                try:
                    with httpx.Client(timeout=45.0) as client:
                        resp = client.post(url, headers=headers, json=payload)

                        if resp.status_code == 200:
                            data = resp.json()
                            raw_content = data["choices"][0]["message"]["content"].strip()
                            translations = self._parse_translations_from_response(raw_content, len(chunk), chunk)

                            all_translated.extend(translations)
                            success = True
                            break

                        elif resp.status_code == 429:
                            retry_after = 2.5
                            try:
                                h_retry = resp.headers.get("retry-after")
                                if h_retry:
                                    retry_after = float(h_retry)
                                else:
                                    err_msg = resp.json().get("error", {}).get("message", "")
                                    m_wait = re.search(r"try again in ([\d\.]+)s", err_msg, re.IGNORECASE)
                                    if m_wait:
                                        retry_after = float(m_wait.group(1)) + 0.5
                            except Exception:
                                pass

                            cooldown = min(max(retry_after, 2.0), 8.0)
                            self._model_cooldowns[try_model] = time.time() + cooldown
                            print(f"[Groq Engine] Limite de débit (429) sur {try_model}. Cooldown {cooldown:.1f}s, bascule immédiate sur le modèle suivant.")
                            time.sleep(0.2)

                        elif resp.status_code == 400:
                            print(f"[Groq Engine] HTTP 400 sur {try_model}: {resp.text[:200]}, bascule de modèle.")
                            self._model_cooldowns[try_model] = time.time() + 1.0
                            time.sleep(0.3)

                        else:
                            print(f"[Groq Engine] HTTP {resp.status_code} sur {try_model}: {resp.text[:200]}")
                            self._model_cooldowns[try_model] = time.time() + 2.0
                            time.sleep(0.5)

                except Exception as e:
                    print(f"[Groq Engine] Exception sur {try_model}: {e}")
                    self._model_cooldowns[try_model] = time.time() + 2.0
                    time.sleep(0.5)

            if not success:
                print(f"[Groq Engine] Attention: Échec des {max_attempts} tentatives pour le groupe de {len(chunk)} éléments.")
                all_translated.extend(chunk)

            # Cadencement poli de 0.4s entre les requêtes pour ne jamais saturer le débit (RPM)
            time.sleep(0.4)

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
