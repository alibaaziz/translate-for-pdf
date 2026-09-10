import os
import re
import fitz  # PyMuPDF
try:
    from PyQt6.QtGui import QImage, QPixmap
except ImportError:
    QImage = None
    QPixmap = None
from config import SYSTEM_FONTS

FIGURE_REGEX = re.compile(
    r'^\s*(?:Fig(?:ure)?|Photo|Tab(?:le)?|Graph(?:ique)?|Diagram(?:me)?|Chart|Schema|Planche)\b',
    re.IGNORECASE
)

# Try bidi and arabic_reshaper for RTL languages (Arabic, Hebrew, Farsi, Urdu)
try:
    import arabic_reshaper
    ARABIC_RESHAPER_AVAILABLE = True
except ImportError:
    ARABIC_RESHAPER_AVAILABLE = False

try:
    import bidi.algorithm
    BIDI_AVAILABLE = True
except ImportError:
    BIDI_AVAILABLE = False

_FONT_OBJ_CACHE = {}
_DUMMY_DOC = None
_DUMMY_PAGE = None


def _get_dummy_page():
    global _DUMMY_DOC, _DUMMY_PAGE
    if _DUMMY_PAGE is None:
        _DUMMY_DOC = fitz.open()
        _DUMMY_PAGE = _DUMMY_DOC.new_page(width=2000, height=3000)
    return _DUMMY_PAGE


class PdfProcessor:
    """
    Advanced PDF Processor guaranteeing layout preservation:
    - 100% preservation of images and vector graphics
    - Strict preservation of font types (Serif vs Sans vs Mono), bold, italic
    - Accurate alignment detection (Centered, Left, Right)
    - Case preservation (ALL CAPS, Title Case)
    - Obstacle / Image collision avoidance (prevents text from covering photos)
    - Column & Table of Contents alignment retention
    """

    @staticmethod
    def render_page_to_qpixmap(doc: fitz.Document, page_num: int, zoom: float = 1.0) -> QPixmap:
        """
        Renders a PDF page to high-quality QPixmap for PyQt6 preview.
        """
        if not doc or page_num < 0 or page_num >= len(doc):
            return QPixmap()

        page = doc.load_page(page_num)
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888
        )
        return QPixmap.fromImage(qimg.copy())

    @staticmethod
    def extract_sample_text_for_detection(doc: fitz.Document, max_pages: int = 3) -> str:
        """
        Extracts sample text from the first few pages to detect document language.
        """
        if not doc:
            return ""

        text_parts = []
        for i in range(min(len(doc), max_pages)):
            page = doc.load_page(i)
            t = page.get_text("text").strip()
            if t:
                text_parts.append(t)

        return "\n".join(text_parts)

    @staticmethod
    def _int_to_rgb_tuple(color_int: int):
        """
        Convert PyMuPDF integer color (sRGB) to float (r, g, b) between 0.0 and 1.0.
        """
        if not color_int or color_int < 0:
            return (0.0, 0.0, 0.0)
        r = ((color_int >> 16) & 255) / 255.0
        g = ((color_int >> 8) & 255) / 255.0
        b = (color_int & 255) / 255.0
        return (r, g, b)

    @classmethod
    def get_font_and_file(cls, font_name: str, flags: int, target_lang: str = "fr"):
        """
        Maps the original PDF font and style flags into the best matching font and fontfile.
        - Uses Windows TrueType fonts whenever available for 100% Unicode support (accents, curly quotes, dashes).
        - Falls back gracefully to standard PDF Base 14 fonts.
        """
        win_fonts = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
        fn_lower = font_name.lower() if font_name else ""
        
        is_bold = (
            (flags & 16 != 0) or 
            any(w in fn_lower for w in ["bold", "black", "heavy", "semibold", "demi", "medium"]) or
            "bd" in fn_lower
        )
        is_italic = (
            (flags & 2 != 0) or 
            any(w in fn_lower for w in ["italic", "oblique", "slanted"]) or
            "it" in fn_lower
        )
        is_serif = any(w in fn_lower for w in [
            "times", "serif", "roman", "georgia", "cambria", "garamond", "minion", "baskerville", "palatino"
        ])
        is_mono = any(w in fn_lower for w in ["courier", "mono", "consolas", "typewriter", "menlo"])

        # 1. Arabic & RTL (uses Arial with full Arabic cursive support)
        if target_lang in ("ar", "he", "fa", "ur"):
            f_bold = os.path.join(win_fonts, "arialbd.ttf")
            f_reg = os.path.join(win_fonts, "arial.ttf")
            f_path = f_bold if (is_bold and os.path.exists(f_bold)) else f_reg
            return ("f_ar_bold" if is_bold else "f_ar_reg", f_path, is_bold)

        # 2. Chinese (uses Microsoft YaHei)
        elif target_lang in ("zh",):
            f_bold = os.path.join(win_fonts, "msyhbd.ttc")
            f_reg = os.path.join(win_fonts, "msyh.ttc")
            f_path = f_bold if (is_bold and os.path.exists(f_bold)) else f_reg
            return ("f_zh_bold" if is_bold else "f_zh_reg", f_path, is_bold)

        # 3. Japanese (uses MS Gothic)
        elif target_lang in ("ja",):
            f_path = os.path.join(win_fonts, "msgothic.ttc")
            return ("f_ja_reg", f_path, is_bold)

        # 4. Hindi (uses Nirmala UI)
        elif target_lang in ("hi",):
            f_bold = os.path.join(win_fonts, "nirmalab.ttf")
            f_reg = os.path.join(win_fonts, "nirmala.ttf")
            f_path = f_bold if (is_bold and os.path.exists(f_bold)) else f_reg
            return ("f_hi_bold" if is_bold else "f_hi_reg", f_path, is_bold)

        # 5. Russian / Cyrillic
        elif target_lang in ("ru", "bg", "uk", "be"):
            f_bold = os.path.join(win_fonts, "arialbd.ttf")
            f_reg = os.path.join(win_fonts, "arial.ttf")
            f_path = f_bold if (is_bold and os.path.exists(f_bold)) else f_reg
            return ("f_cyrillic_bold" if is_bold else "f_cyrillic_reg", f_path, is_bold)

        # 6. Standard Western / Latin (French, Spanish, German, Italian, etc.)
        # Prefer Windows TrueType fonts to ensure full Unicode support (accents, curly quotes, dashes)
        if os.path.isdir(win_fonts):
            if is_serif:
                if is_bold and is_italic:
                    f = os.path.join(win_fonts, "timesbi.ttf")
                    if os.path.exists(f): return ("f_serif_bi", f, is_bold)
                elif is_bold:
                    f = os.path.join(win_fonts, "timesbd.ttf")
                    if os.path.exists(f): return ("f_serif_b", f, is_bold)
                elif is_italic:
                    f = os.path.join(win_fonts, "timesi.ttf")
                    if os.path.exists(f): return ("f_serif_i", f, is_bold)
                else:
                    f = os.path.join(win_fonts, "times.ttf")
                    if os.path.exists(f): return ("f_serif_r", f, is_bold)
            elif is_mono:
                if is_bold:
                    f = os.path.join(win_fonts, "courbd.ttf")
                    if os.path.exists(f): return ("f_mono_b", f, is_bold)
                else:
                    f = os.path.join(win_fonts, "cour.ttf")
                    if os.path.exists(f): return ("f_mono_r", f, is_bold)
            else:
                if is_bold and is_italic:
                    f = os.path.join(win_fonts, "arialbi.ttf")
                    if os.path.exists(f): return ("f_sans_bi", f, is_bold)
                elif is_bold:
                    f = os.path.join(win_fonts, "arialbd.ttf")
                    if os.path.exists(f): return ("f_sans_b", f, is_bold)
                elif is_italic:
                    f = os.path.join(win_fonts, "ariali.ttf")
                    if os.path.exists(f): return ("f_sans_i", f, is_bold)
                else:
                    f = os.path.join(win_fonts, "arial.ttf")
                    if os.path.exists(f): return ("f_sans_r", f, is_bold)

        # Fallback to standard PDF Base 14 fonts
        if is_serif:
            if is_bold and is_italic:
                return ("times-bolditalic", None, is_bold)
            elif is_bold:
                return ("times-bold", None, is_bold)
            elif is_italic:
                return ("times-italic", None, is_bold)
            else:
                return ("times-roman", None, is_bold)
        elif is_mono:
            if is_bold:
                return ("courier-bold", None, is_bold)
            else:
                return ("courier", None, is_bold)
        else:
            if is_bold and is_italic:
                return ("hebi", None, is_bold)
            elif is_bold:
                return ("hebo", None, is_bold)
            elif is_italic:
                return ("heit", None, is_bold)
            else:
                return ("helv", None, is_bold)

    @classmethod
    def _format_arabic_rtl_text(cls, text: str, max_width: float, fontsize: float, fontfile: str = None) -> str:
        """
        Shapes Arabic characters (ligatures, initial/medial/final forms) and calculates
        per-line BiDi display with word-wrapping so multiline Arabic flows naturally
        from top to bottom and right to left.
        """
        if not text:
            return ""

        # Step 1: Arabic reshaping (joining cursive characters)
        if ARABIC_RESHAPER_AVAILABLE:
            try:
                reshaped = arabic_reshaper.reshape(text)
            except Exception:
                reshaped = text
        else:
            reshaped = text

        if not BIDI_AVAILABLE:
            return reshaped

        # Cache font object for accurate character measuring
        win_fonts = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
        f_path = fontfile or os.path.join(win_fonts, "arial.ttf")
        if f_path not in _FONT_OBJ_CACHE:
            if os.path.exists(f_path):
                try:
                    _FONT_OBJ_CACHE[f_path] = fitz.Font(fontfile=f_path)
                except Exception:
                    _FONT_OBJ_CACHE[f_path] = None
            else:
                _FONT_OBJ_CACHE[f_path] = None

        font_obj = _FONT_OBJ_CACHE.get(f_path)

        words = reshaped.split(" ")
        lines = []
        curr_words = []

        for w in words:
            trial = " ".join(curr_words + [w])
            if font_obj:
                try:
                    w_len = font_obj.text_length(trial, fontsize=fontsize)
                except Exception:
                    w_len = len(trial) * fontsize * 0.55
            else:
                w_len = len(trial) * fontsize * 0.55

            if w_len > max_width and curr_words:
                lines.append(bidi.algorithm.get_display(" ".join(curr_words)))
                curr_words = [w]
            else:
                curr_words.append(w)

        if curr_words:
            lines.append(bidi.algorithm.get_display(" ".join(curr_words)))

        return "\n".join(lines)

    @staticmethod
    def detect_alignment(rect: fitz.Rect, page_width: float, is_single_short_line: bool = False, num_lines: int = 1) -> int:
        """
        Detects if text is centered on the page, right-aligned, or left-aligned.
        fitz.TEXT_ALIGN_LEFT = 0
        fitz.TEXT_ALIGN_CENTER = 1
        fitz.TEXT_ALIGN_RIGHT = 2
        """
        mid_x = (rect.x0 + rect.x1) / 2.0
        page_mid = page_width / 2.0
        
        # Centered titles / headers:
        # A block is only considered centered if it's relatively short and centered on page,
        # NOT a full-width paragraph that spans across the margins!
        if num_lines <= 2 and (rect.x1 - rect.x0) < page_width * 0.65 and abs(mid_x - page_mid) < 25:
            return fitz.TEXT_ALIGN_CENTER
            
        # Far-right aligned items (page numbers, right column headers)
        if rect.x0 > page_width * 0.70 or (is_single_short_line and rect.x0 > page_width * 0.55):
            return fitz.TEXT_ALIGN_RIGHT
            
        return fitz.TEXT_ALIGN_LEFT

    @staticmethod
    def preserve_case(original_text: str, translated_text: str, target_lang: str = "fr") -> str:
        """
        Preserves text capitalization (e.g. ALL CAPS for titles like DESIGN AND CONSTRUCTION OF TUNNELS).
        Bypasses scripts without case (Arabic, Chinese, Japanese, Hindi).
        """
        if not original_text or not translated_text:
            return translated_text

        if target_lang in ("ar", "he", "fa", "ur", "zh", "ja", "hi", "ko"):
            return translated_text

        # If original text is ALL UPPERCASE (and more than 2 chars)
        alpha_chars = [c for c in original_text if c.isalpha()]
        if len(alpha_chars) >= 3 and original_text.isupper():
            return translated_text.upper()

        # If original text is Title Case (e.g. 'About the Author')
        if original_text.istitle() and len(original_text.split()) > 1:
            return translated_text.capitalize()

        return translated_text

    @classmethod
    def extract_visual_units(cls, page: fitz.Page, target_lang: str = "fr"):
        """
        Extracts cohesive visual text units:
        - Prevents grouping columns on the same row into a single block
        - Prevents wrap-around text from bridging over images
        - Isolates titles from body paragraphs
        - Detects font weight and style changes
        - Adapts alignment and font mapping for target language
        """
        page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_SEARCH)
        page_width = page.rect.width
        image_rects = [fitz.Rect(info["bbox"]) for info in page.get_image_info()]

        units = []

        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:
                continue

            lines = b.get("lines", [])
            if not lines:
                continue

            current_group = []

            for l in lines:
                l_rect = fitz.Rect(l["bbox"])
                l_spans = l.get("spans", [])
                l_text = "".join(s.get("text", "") for s in l_spans).strip()
                if not l_text:
                    continue

                span0 = l_spans[0]
                is_bold = (span0.get("flags", 0) & 16 != 0) or "bold" in span0.get("font", "").lower()
                font_size = span0.get("size", 10.0)

                if not current_group:
                    current_group.append((l, l_rect, l_text, span0, is_bold, font_size))
                    continue

                prev_l, prev_rect, prev_text, prev_span0, prev_bold, prev_size = current_group[-1]

                # 1. Check if line crosses an image vertical boundary compared to prev line (wrap-around next to figure)
                crosses_img = False
                for img_r in image_rects:
                    prev_in = (prev_rect.y1 > img_r.y0 and prev_rect.y0 < img_r.y1)
                    curr_in = (l_rect.y1 > img_r.y0 and l_rect.y0 < img_r.y1)
                    if prev_in != curr_in:
                        crosses_img = True
                        break

                if crosses_img:
                    units.append(current_group)
                    current_group = [(l, l_rect, l_text, span0, is_bold, font_size)]
                    continue

                # 2. Check for column collision on same row (y overlap with horizontal gap)
                y_overlap = min(l_rect.y1, prev_rect.y1) - max(l_rect.y0, prev_rect.y0)
                if y_overlap > 3.0:
                    units.append(current_group)
                    current_group = [(l, l_rect, l_text, span0, is_bold, font_size)]
                    continue

                # 3. Check for indentation jumps (e.g. wrap-around next to an image)
                if abs(l_rect.x0 - prev_rect.x0) > 30.0:
                    units.append(current_group)
                    current_group = [(l, l_rect, l_text, span0, is_bold, font_size)]
                    continue

                # 4. Check for font style shifts (Heading bold vs body regular)
                if is_bold != prev_bold or abs(font_size - prev_size) > 2.5:
                    units.append(current_group)
                    current_group = [(l, l_rect, l_text, span0, is_bold, font_size)]
                    continue

                # Same cohesive paragraph
                current_group.append((l, l_rect, l_text, span0, is_bold, font_size))

            if current_group:
                units.append(current_group)

        # Assemble and refine each visual unit
        refined_units = []
        for group in units:
            union_rect = fitz.Rect(group[0][1])
            for item in group[1:]:
                union_rect |= item[1]

            unit_text = " ".join(item[2] for item in group).strip()
            if not unit_text:
                continue

            first_span = group[0][3]
            font_name = first_span.get("font", "")
            flags = first_span.get("flags", 0)
            font_size = group[0][5]
            color_int = first_span.get("color", 0)
            rgb_color = cls._int_to_rgb_tuple(color_int)
            resolved_font, resolved_file, is_bold = cls.get_font_and_file(font_name, flags, target_lang=target_lang)
            is_single = len(group) == 1 and len(unit_text) < 40
            alignment = cls.detect_alignment(union_rect, page_width, is_single_short_line=is_single, num_lines=len(group))

            # Adapt alignment for RTL languages (e.g. Arabic, Hebrew)
            if target_lang in ("ar", "he", "fa", "ur"):
                if alignment == fitz.TEXT_ALIGN_LEFT:
                    alignment = fitz.TEXT_ALIGN_RIGHT

            is_fig = bool(FIGURE_REGEX.match(unit_text))
            is_inside_image = any(
                img_r.contains(union_rect) or
                (union_rect.intersects(img_r) and (union_rect & img_r).get_area() > 0.6 * union_rect.get_area())
                for img_r in image_rects
            )

            line_rects = [fitz.Rect(item[1]) for item in group]

            refined_units.append({
                "rect": union_rect,
                "line_rects": line_rects,
                "original_text": unit_text,
                "fontsize": font_size,
                "fontname": resolved_font,
                "fontfile": resolved_file,
                "color": rgb_color,
                "align": alignment,
                "num_lines": len(group),
                "is_bold": is_bold,
                "is_figure": is_fig or is_inside_image
            })

        # Allow isolated short labels some horizontal breathing room if unconstrained
        for u in refined_units:
            if u.get("is_figure", False):
                continue
            if u["num_lines"] == 1 and len(u["original_text"]) < 30:
                can_expand_left = True
                can_expand_right = True
                for other in refined_units:
                    if other is u:
                        continue
                    y_overlap = min(u["rect"].y1, other["rect"].y1) - max(u["rect"].y0, other["rect"].y0)
                    if y_overlap > 0:
                        if 0 <= (u["rect"].x0 - other["rect"].x1) < 20:
                            can_expand_left = False
                        if 0 <= (other["rect"].x0 - u["rect"].x1) < 20:
                            can_expand_right = False
                if can_expand_left and u["rect"].x0 > 35:
                    u["rect"].x0 -= 15.0
                if can_expand_right and u["rect"].x1 < page_width - 35:
                    u["rect"].x1 += 15.0

        return refined_units

    @classmethod
    def _insert_text_autofit(cls, page: fitz.Page, rect: fitz.Rect, text: str,
                             initial_fontsize: float, fontname: str = "helv",
                             fontfile: str = None,
                             color=(0.0, 0.0, 0.0), align: int = 0,
                             target_lang: str = "fr", num_lines: int = 1,
                             is_bold: bool = False) -> bool:
        """
        Dynamically fits translated text into rect using auto-scaling typography.
        Preserves font type, weight, alignment, and original visual size.
        Supports complex RTL scripts (Arabic, Hebrew) and Asian scripts.
        """
        if not text or not text.strip():
            return True

        is_rtl = target_lang in ("ar", "he", "fa", "ur")

        encoding = fitz.TEXT_ENCODING_LATIN
        if target_lang in ("ru", "bg", "uk", "be"):
            encoding = fitz.TEXT_ENCODING_CYRILLIC
        elif target_lang in ("el",):
            encoding = fitz.TEXT_ENCODING_GREEK

        # Keep fit rect tightly within the original visual bounds to prevent overlapping adjacent lines
        extra_h = 1.5 if num_lines == 1 else 2.0
        fit_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + extra_h)

        base_kwargs = {
            "color": color,
            "align": align,
            "fontname": fontname
        }
        if fontfile:
            base_kwargs["fontfile"] = fontfile
        elif encoding:
            base_kwargs["encoding"] = encoding

        dummy = _get_dummy_page()
        best_fs = None
        best_text = text
        cur_fs = initial_fontsize
        min_fs = max(4.5, initial_fontsize * 0.60)

        # Probe candidate font sizes using dummy page (render_mode=3, invisible) to avoid overdrawing
        while cur_fs >= min_fs:
            if is_rtl:
                trial_text = cls._format_arabic_rtl_text(
                    text=text,
                    max_width=fit_rect.width,
                    fontsize=cur_fs,
                    fontfile=fontfile
                )
            else:
                trial_text = text

            test_kwargs = dict(base_kwargs)
            test_kwargs["fontsize"] = cur_fs
            test_kwargs["render_mode"] = 3
            rc = dummy.insert_textbox(fit_rect, trial_text, **test_kwargs)
            if rc >= 0:
                best_fs = cur_fs
                best_text = trial_text
                break
            cur_fs -= 0.5

        if best_fs is None:
            # Fallback with slightly expanded height tolerance if text is significantly longer
            fallback_rect = fitz.Rect(fit_rect.x0, fit_rect.y0, fit_rect.x1, fit_rect.y1 + 14.0)
            best_fs = min_fs
            if is_rtl:
                best_text = cls._format_arabic_rtl_text(
                    text=text,
                    max_width=fallback_rect.width,
                    fontsize=best_fs,
                    fontfile=fontfile
                )
            else:
                best_text = text
            target_rect = fallback_rect
        else:
            target_rect = fit_rect

        # Perform the actual single clean draw on the target page
        final_kwargs = dict(base_kwargs)
        final_kwargs["fontsize"] = best_fs
        rc = page.insert_textbox(target_rect, best_text, **final_kwargs)
        return rc >= 0

    @classmethod
    def translate_document(cls, input_pdf_path: str, output_pdf_path: str,
                           from_lang: str, to_lang: str,
                           translator_func,
                           skip_figures: bool = True,
                           progress_callback=None,
                           is_cancelled_callback=None) -> bool:
        """
        Performs full document translation with strict preservation of layout,
        images, vector graphics, font styles (Serif, Sans, Bold, Italic),
        alignments, and capitalization. Supports Arabic (RTL) & multilingual fonts.
        When skip_figures is True, all figures, captions, diagrams, and image text
        are preserved 100% untouched in their original vector form without redaction.
        """
        doc = fitz.open(input_pdf_path)
        total_pages = len(doc)

        for page_idx in range(total_pages):
            if is_cancelled_callback and is_cancelled_callback():
                doc.close()
                return False

            if progress_callback:
                progress_callback(page_idx, total_pages, f"Traduction de la page {page_idx + 1} / {total_pages}...")

            page = doc.load_page(page_idx)
            visual_units = cls.extract_visual_units(page, target_lang=to_lang)

            if not visual_units:
                continue

            # 1. Gather all units needing translation on this page
            units_to_translate = []
            texts_to_translate = []

            for unit in visual_units:
                orig_text = unit["original_text"].strip()
                # If skipping figures, skip figure captions, diagrams, and image text
                if skip_figures and (unit.get("is_figure", False) or FIGURE_REGEX.match(orig_text)):
                    unit["is_skipped"] = True
                    unit["translated_text"] = orig_text
                    continue

                # Do not translate standalone numbers or short symbols (e.g. page numbers '385', roman 'XI', bullets)
                if orig_text.replace(".", "").replace(",", "").replace("-", "").isdigit() or (len(orig_text) <= 1 and not orig_text.isalnum()):
                    unit["is_skipped"] = True
                    unit["translated_text"] = orig_text
                else:
                    unit["is_skipped"] = False
                    units_to_translate.append(unit)
                    texts_to_translate.append(orig_text)

            # 2. Batch-translate all texts on this page in ONE parallel GPU pass
            if texts_to_translate:
                if is_cancelled_callback and is_cancelled_callback():
                    doc.close()
                    return False

                if hasattr(translator_func, "translate_batch_texts"):
                    batch_fn = translator_func.translate_batch_texts
                elif hasattr(translator_func, "__self__") and hasattr(translator_func.__self__, "translate_batch_texts"):
                    batch_fn = translator_func.__self__.translate_batch_texts
                else:
                    batch_fn = None

                if batch_fn:
                    translated_list = batch_fn(texts_to_translate, from_lang, to_lang)
                else:
                    translated_list = [translator_func(t, from_lang, to_lang) for t in texts_to_translate]

                for u, trans in zip(units_to_translate, translated_list):
                    u["translated_text"] = cls.preserve_case(u["original_text"], trans, target_lang=to_lang)

            # 2. Delete any existing form widgets/annotations on this page to prevent overlap
            for w in list(page.widgets()):
                page.delete_widget(w)

            # Redact original text strictly within exact line rects (skipping untouched symbols and skipped figures)
            for unit in visual_units:
                if unit.get("is_skipped", False):
                    continue
                orig_text = unit["original_text"].strip()
                if len(orig_text) <= 1 and not orig_text.isalnum():
                    continue
                for l_rect in unit.get("line_rects", [unit["rect"]]):
                    page.add_redact_annot(l_rect, fill=False)

            # Apply redaction without touching images or drawings
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE
            )

            # 3. Re-insert translated text with resolved font, bold/italic, alignment, and auto-fit
            for unit in visual_units:
                if unit.get("is_skipped", False):
                    continue
                orig_text = unit["original_text"].strip()
                if len(orig_text) <= 1 and not orig_text.isalnum():
                    continue
                cls._insert_text_autofit(
                    page=page,
                    rect=unit["rect"],
                    text=unit["translated_text"],
                    initial_fontsize=unit["fontsize"],
                    fontname=unit["fontname"],
                    fontfile=unit.get("fontfile"),
                    color=unit["color"],
                    align=unit["align"],
                    target_lang=to_lang,
                    num_lines=unit["num_lines"],
                    is_bold=unit.get("is_bold", False)
                )

        # 4. Save the final translated PDF with deflated compression
        doc.save(output_pdf_path, garbage=3, deflate=True)
        doc.close()

        if progress_callback:
            progress_callback(total_pages, total_pages, "Traduction terminée avec succès !")

        return True
