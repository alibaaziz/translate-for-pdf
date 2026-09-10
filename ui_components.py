import fitz
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QSpinBox, QSlider, QFrame, QSizePolicy
)
from pdf_processor import PdfProcessor


class TranslationWorker(QThread):
    """
    Background worker thread for translating PDF documents without blocking the UI.
    """
    progress_signal = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, input_path: str, output_path: str, from_lang: str, to_lang: str, translator_func, engine=None, skip_figures: bool = True):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.from_lang = from_lang
        self.to_lang = to_lang
        self.translator_func = translator_func
        self.engine = engine
        self.skip_figures = skip_figures
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if self.engine and not self.engine.is_package_installed(self.from_lang, self.to_lang):
                self.progress_signal.emit(0, 100, "Téléchargement du modèle de langue...")
                self.engine.install_language_pair(
                    self.from_lang,
                    self.to_lang,
                    progress_callback=lambda msg: self.progress_signal.emit(0, 100, msg)
                )

            def on_progress(cur, total, msg):
                self.progress_signal.emit(cur, total, msg)

            def is_cancelled():
                return self._is_cancelled

            success = PdfProcessor.translate_document(
                input_pdf_path=self.input_path,
                output_pdf_path=self.output_path,
                from_lang=self.from_lang,
                to_lang=self.to_lang,
                translator_func=self.translator_func,
                skip_figures=self.skip_figures,
                progress_callback=on_progress,
                is_cancelled_callback=is_cancelled
            )

            if self._is_cancelled:
                self.finished_signal.emit(False, "", "Traduction annulée par l'utilisateur.")
            elif success:
                self.finished_signal.emit(True, self.output_path, "")
            else:
                self.finished_signal.emit(False, "", "Échec de la traduction du PDF.")
        except Exception as e:
            self.finished_signal.emit(False, "", str(e))


class PdfPageView(QLabel):
    """
    Widget displaying a single page rendered from a PDF document.
    """
    def __init__(self, placeholder_text: str = "Aucun aperçu"):
        super().__init__()
        self.placeholder_text = placeholder_text
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                background-color: #f1f5f9;
                color: #64748b;
                font-size: 14px;
                font-weight: 500;
                border: 1px dashed #cbd5e1;
                border-radius: 6px;
            }
        """)
        self.setText(self.placeholder_text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_page_pixmap(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            self.setPixmap(pixmap)
            self.setStyleSheet("""
                QLabel {
                    background-color: #ffffff;
                    border: 1px solid #d1d5db;
                    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                }
            """)
            self.adjustSize()
        else:
            self.setPixmap(QPixmap())
            self.setText(self.placeholder_text)
            self.setStyleSheet("""
                QLabel {
                    background-color: #f1f5f9;
                    color: #64748b;
                    font-size: 14px;
                    border: 1px dashed #cbd5e1;
                    border-radius: 6px;
                }
            """)


class ScrollRuleWidget(QFrame):
    """
    Navigation and synchronized scroll control bar ('Règle de scroll').
    """
    page_changed = pyqtSignal(int)
    zoom_changed = pyqtSignal(float)
    fit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = 0
        self.total_pages = 1
        self.zoom = 1.0

        self.setFixedWidth(64)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border-radius: 8px;
                border: 1px solid #334155;
            }
            QLabel {
                color: #f8fafc;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                border: 1px solid #475569;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #3b82f6;
                border-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
            QSlider::groove:vertical {
                background: #334155;
                width: 6px;
                border-radius: 3px;
            }
            QSlider::handle:vertical {
                background: #38bdf8;
                height: 16px;
                margin: 0 -5px;
                border-radius: 8px;
            }
            QSlider::handle:vertical:hover {
                background: #0284c7;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)

        # Title / Label
        title = QLabel("NAV")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Next / Prev buttons
        self.btn_prev = QPushButton("▲")
        self.btn_prev.setToolTip("Page précédente")
        self.btn_prev.clicked.connect(self._prev_page)
        layout.addWidget(self.btn_prev)

        # Page Label
        self.lbl_page = QLabel("1/1")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_page)

        self.btn_next = QPushButton("▼")
        self.btn_next.setToolTip("Page suivante")
        self.btn_next.clicked.connect(self._next_page)
        layout.addWidget(self.btn_next)

        # Vertical Slider for quick page navigation
        layout.addSpacing(10)
        self.page_slider = QSlider(Qt.Orientation.Vertical)
        self.page_slider.setRange(1, 1)
        self.page_slider.setValue(1)
        self.page_slider.setInvertedAppearance(True)
        self.page_slider.valueChanged.connect(self._on_slider_page_changed)
        layout.addWidget(self.page_slider, 1, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(10)

        # Zoom Controls
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setToolTip("Zoom avant")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        layout.addWidget(self.btn_zoom_in)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_zoom)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setToolTip("Zoom arrière")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        layout.addWidget(self.btn_zoom_out)

        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setToolTip("Ajuster à la largeur")
        self.btn_fit.clicked.connect(self._fit_width)
        layout.addWidget(self.btn_fit)

    def set_document_info(self, total_pages: int, current_page: int = 0):
        self.total_pages = max(1, total_pages)
        self.current_page = min(max(0, current_page), self.total_pages - 1)
        self.page_slider.blockSignals(True)
        self.page_slider.setRange(1, self.total_pages)
        self.page_slider.setValue(self.current_page + 1)
        self.page_slider.blockSignals(False)
        self.lbl_page.setText(f"{self.current_page + 1}/{self.total_pages}")
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled(self.current_page < self.total_pages - 1)

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.set_document_info(self.total_pages, self.current_page)
            self.page_changed.emit(self.current_page)

    def _next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.set_document_info(self.total_pages, self.current_page)
            self.page_changed.emit(self.current_page)

    def _on_slider_page_changed(self, value: int):
        target_page = value - 1
        if target_page != self.current_page and 0 <= target_page < self.total_pages:
            self.current_page = target_page
            self.lbl_page.setText(f"{self.current_page + 1}/{self.total_pages}")
            self.btn_prev.setEnabled(self.current_page > 0)
            self.btn_next.setEnabled(self.current_page < self.total_pages - 1)
            self.page_changed.emit(self.current_page)

    def _zoom_in(self):
        if self.zoom < 2.5:
            self.zoom = round(self.zoom + 0.15, 2)
            self.lbl_zoom.setText(f"{int(self.zoom * 100)}%")
            self.zoom_changed.emit(self.zoom)

    def _zoom_out(self):
        if self.zoom > 0.4:
            self.zoom = round(self.zoom - 0.15, 2)
            self.lbl_zoom.setText(f"{int(self.zoom * 100)}%")
            self.zoom_changed.emit(self.zoom)

    def _fit_width(self):
        self.fit_requested.emit()

    def set_zoom_display(self, zoom_val: float):
        self.zoom = round(zoom_val, 2)
        self.lbl_zoom.setText(f"{int(self.zoom * 100)}%")


class SynchronizedDualPdfViewer(QWidget):
    """
    Dual PDF viewer with synchronized scrolling, page navigation, and zooming.
    Left: Source PDF Preview.
    Right: Translated PDF Preview.
    Left Bar: 'Règle de scroll' and page controls.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_doc = None
        self.translated_doc = None
        self.current_page = 0
        self.zoom = 1.0
        self._sync_lock = False

        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(8)

        # 1. Scroll Rule / Navigation Bar
        self.scroll_rule = ScrollRuleWidget()
        self.scroll_rule.page_changed.connect(self._on_page_changed)
        self.scroll_rule.zoom_changed.connect(self._on_zoom_changed)
        self.scroll_rule.fit_requested.connect(self.fit_to_width)
        main_layout.addWidget(self.scroll_rule)

        # 2. Source PDF Container
        source_container = QVBoxLayout()
        source_header = QLabel("Aperçu Fichier source")
        source_header.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: #1e3a8a;
            padding: 4px 8px;
            background-color: #dbeafe;
            border-radius: 4px;
        """)
        source_container.addWidget(source_header)

        self.scroll_source = QScrollArea()
        self.scroll_source.setWidgetResizable(True)
        self.scroll_source.setStyleSheet("background-color: #cbd5e1; border: 1px solid #94a3b8; border-radius: 6px;")
        
        self.source_view = PdfPageView("Sélectionnez un fichier PDF à gauche")
        self.scroll_source.setWidget(self.source_view)
        source_container.addWidget(self.scroll_source, 1)

        main_layout.addLayout(source_container, 1)

        # 3. Translated PDF Container
        trans_container = QVBoxLayout()
        trans_header = QLabel("Aperçu Fichier traduit")
        trans_header.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: #14532d;
            padding: 4px 8px;
            background-color: #dcfce7;
            border-radius: 4px;
        """)
        trans_container.addWidget(trans_header)

        self.scroll_translated = QScrollArea()
        self.scroll_translated.setWidgetResizable(True)
        self.scroll_translated.setStyleSheet("background-color: #cbd5e1; border: 1px solid #94a3b8; border-radius: 6px;")

        self.translated_view = PdfPageView("En attente de la traduction...")
        self.scroll_translated.setWidget(self.translated_view)
        trans_container.addWidget(self.scroll_translated, 1)

        main_layout.addLayout(trans_container, 1)

        # Synchronize Vertical and Horizontal Scrollbars
        self.scroll_source.verticalScrollBar().valueChanged.connect(self._sync_scroll_from_source)
        self.scroll_translated.verticalScrollBar().valueChanged.connect(self._sync_scroll_from_translated)
        self.scroll_source.horizontalScrollBar().valueChanged.connect(self._sync_hscroll_from_source)
        self.scroll_translated.horizontalScrollBar().valueChanged.connect(self._sync_hscroll_from_translated)

    def _sync_scroll_from_source(self, val):
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            src_max = self.scroll_source.verticalScrollBar().maximum()
            tgt_max = self.scroll_translated.verticalScrollBar().maximum()
            if src_max > 0 and tgt_max > 0:
                ratio = val / src_max
                self.scroll_translated.verticalScrollBar().setValue(int(ratio * tgt_max))
            else:
                self.scroll_translated.verticalScrollBar().setValue(val)
        finally:
            self._sync_lock = False

    def _sync_scroll_from_translated(self, val):
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            src_max = self.scroll_source.verticalScrollBar().maximum()
            tgt_max = self.scroll_translated.verticalScrollBar().maximum()
            if tgt_max > 0 and src_max > 0:
                ratio = val / tgt_max
                self.scroll_source.verticalScrollBar().setValue(int(ratio * src_max))
            else:
                self.scroll_source.verticalScrollBar().setValue(val)
        finally:
            self._sync_lock = False

    def _sync_hscroll_from_source(self, val):
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            self.scroll_translated.horizontalScrollBar().setValue(val)
        finally:
            self._sync_lock = False

    def _sync_hscroll_from_translated(self, val):
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            self.scroll_source.horizontalScrollBar().setValue(val)
        finally:
            self._sync_lock = False

    def set_source_document(self, doc: fitz.Document):
        self.source_doc = doc
        self.current_page = 0
        total = len(doc) if doc else 1
        self.scroll_rule.set_document_info(total, 0)
        self.fit_to_width()

    def set_translated_document(self, doc: fitz.Document):
        self.translated_doc = doc
        self.render_current_pages()

    def render_current_pages(self):
        # Render source page
        if self.source_doc and 0 <= self.current_page < len(self.source_doc):
            pix_src = PdfProcessor.render_page_to_qpixmap(self.source_doc, self.current_page, self.zoom)
            self.source_view.set_page_pixmap(pix_src)
        else:
            self.source_view.set_page_pixmap(None)

        # Render translated page
        if self.translated_doc and 0 <= self.current_page < len(self.translated_doc):
            pix_tgt = PdfProcessor.render_page_to_qpixmap(self.translated_doc, self.current_page, self.zoom)
            self.translated_view.set_page_pixmap(pix_tgt)
        else:
            self.translated_view.set_page_pixmap(None)

    def _on_page_changed(self, page_num: int):
        self.current_page = page_num
        self.render_current_pages()
        self.scroll_source.verticalScrollBar().setValue(0)
        self.scroll_translated.verticalScrollBar().setValue(0)

    def _on_zoom_changed(self, zoom_val: float):
        self.zoom = zoom_val
        self.render_current_pages()

    def fit_to_width(self):
        doc = self.source_doc or self.translated_doc
        if doc and 0 <= self.current_page < len(doc):
            viewport_w = self.scroll_source.viewport().width() - 24
            page_w = doc[self.current_page].rect.width
            if viewport_w > 50 and page_w > 0:
                new_zoom = max(0.4, min(2.5, viewport_w / page_w))
                self.zoom = round(new_zoom, 2)
                self.scroll_rule.set_zoom_display(self.zoom)
                self.render_current_pages()
