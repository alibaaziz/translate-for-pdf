import os
import shutil
import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFileDialog, QProgressBar,
    QMessageBox, QSplitter, QGroupBox, QFrame, QCheckBox
)

from config import SUPPORTED_LANGUAGES, LANGUAGE_CODE_TO_NAME
from translator_engine import NllbTranslatorEngine
from pdf_processor import PdfProcessor
from ui_components import SynchronizedDualPdfViewer, TranslationWorker


class MainWindow(QMainWindow):
    """
    Main Application Window strictly following the user's interface layout:
    Left: Controls, Language selection, Translation and Save buttons.
    Right: Synchronized Dual PDF Viewer with Scroll Rule and Previews.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Traducteur de Documents PDF Hors-Ligne (Meta NLLB-200)")
        self.resize(1350, 850)
        self.setMinimumSize(950, 600)

        # Core engine powered exclusively by Meta NLLB-200
        self.translator_engine = NllbTranslatorEngine()
        self.source_pdf_path = None
        self.translated_pdf_path = None
        self.source_doc = None
        self.translated_doc = None
        self.worker = None

        self._init_ui()
        self._apply_styling()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main horizontal splitter or layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. LEFT PANEL : CONTROLS & SETTINGS (Conform to user sketch)
        # -------------------------------------------------------------
        left_panel = QFrame()
        left_panel.setFixedWidth(330)
        left_panel.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 16, 14, 16)
        left_layout.setSpacing(16)

        # Button: Choisir fichier pdf
        self.btn_choose_pdf = QPushButton("Choisir fichier pdf")
        self.btn_choose_pdf.setObjectName("btnChoosePdf")
        self.btn_choose_pdf.clicked.connect(self._choose_pdf_file)
        left_layout.addWidget(self.btn_choose_pdf)

        # File info label
        self.lbl_file_info = QLabel("Aucun document chargé")
        self.lbl_file_info.setObjectName("lblFileInfo")
        self.lbl_file_info.setWordWrap(True)
        left_layout.addWidget(self.lbl_file_info)

        left_layout.addSpacing(6)

        # Source Language Row : [ Langue source ] [ Detecter langue ]
        lbl_lang_src = QLabel("Langue source")
        lbl_lang_src.setStyleSheet("font-weight: 600; color: #1e293b; font-size: 12px;")
        left_layout.addWidget(lbl_lang_src)

        src_row = QHBoxLayout()
        src_row.setSpacing(8)

        self.combo_source_lang = QComboBox()
        self.combo_source_lang.setObjectName("comboSource")
        src_row.addWidget(self.combo_source_lang, 1)

        self.btn_detect_lang = QPushButton("Detecter langue")
        self.btn_detect_lang.setObjectName("btnDetectLang")
        self.btn_detect_lang.clicked.connect(self._detect_source_language)
        src_row.addWidget(self.btn_detect_lang)

        left_layout.addLayout(src_row)

        left_layout.addSpacing(4)

        # Destination Language : [ Langue destination ]
        lbl_lang_dest = QLabel("Langue destination")
        lbl_lang_dest.setStyleSheet("font-weight: 600; color: #1e293b; font-size: 12px;")
        left_layout.addWidget(lbl_lang_dest)

        self.combo_target_lang = QComboBox()
        self.combo_target_lang.setObjectName("comboTarget")
        left_layout.addWidget(self.combo_target_lang)

        self._refresh_language_combos()

        left_layout.addSpacing(6)

        # Checkbox: Preserve figures & captions (recommended)
        self.chk_skip_figures = QCheckBox("Conserver figures et légendes (Fig., Table...)")
        self.chk_skip_figures.setObjectName("chkSkipFigures")
        self.chk_skip_figures.setChecked(True)
        self.chk_skip_figures.setToolTip(
            "Conserve intégralement les figures, légendes (Fig., Table...), graphiques "
            "et diagrammes dans leur format vectoriel d'origine sans les altérer ni les traduire."
        )
        left_layout.addWidget(self.chk_skip_figures)

        left_layout.addSpacing(10)

        # Purple Action Buttons from user sketch: [ traduire ] & [ enregistrer ]
        self.btn_translate = QPushButton("traduire")
        self.btn_translate.setObjectName("btnTranslate")
        self.btn_translate.clicked.connect(self._start_translation)
        self.btn_translate.setEnabled(False)
        left_layout.addWidget(self.btn_translate)

        self.btn_save = QPushButton("enregistrer")
        self.btn_save.setObjectName("btnSave")
        self.btn_save.clicked.connect(self._save_translated_pdf)
        self.btn_save.setEnabled(False)
        left_layout.addWidget(self.btn_save)

        left_layout.addSpacing(10)

        # Progress and status section
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Prêt.")
        self.lbl_status.setObjectName("lblStatus")
        self.lbl_status.setWordWrap(True)
        left_layout.addWidget(self.lbl_status)

        # Cancel button (hidden by default)
        self.btn_cancel = QPushButton("Annuler la traduction")
        self.btn_cancel.setObjectName("btnCancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_translation)
        left_layout.addWidget(self.btn_cancel)

        left_layout.addStretch(1)

        # Hardware acceleration badge
        device_name = self.translator_engine.active_device_name
        if "CUDA" in device_name:
            accel_text = "⚡ Accélération : NVIDIA CUDA (GPU Actif)"
            accel_style = "color: #15803d; font-size: 11px; font-weight: bold; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 6px; padding: 6px 8px;"
        else:
            accel_text = "🖥️ Accélération : Processeur (CPU)"
            accel_style = "color: #475569; font-size: 11px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px;"
        self.lbl_accel = QLabel(accel_text)
        self.lbl_accel.setStyleSheet(accel_style)
        left_layout.addWidget(self.lbl_accel)

        left_layout.addSpacing(6)

        # Bottom guarantee badge
        lbl_badge = QLabel("✔ Moteur IA Meta NLLB-200 (SOTA)\n✔ Conservation 100% des images\n✔ Conservation intégrale des graphiques\n✔ 100% Hors-ligne & Sécurisé")
        lbl_badge.setStyleSheet("color: #059669; font-size: 11px; background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px; padding: 8px;")
        left_layout.addWidget(lbl_badge)

        main_layout.addWidget(left_panel)

        # -------------------------------------------------------------
        # 2. RIGHT PANEL : DUAL PDF PREVIEWS & SCROLL RULE (Conform to user sketch)
        # -------------------------------------------------------------
        self.dual_viewer = SynchronizedDualPdfViewer()
        main_layout.addWidget(self.dual_viewer, 1)

    def _apply_styling(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8fafc;
            }
            #leftPanel {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
            }
            #btnChoosePdf {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                padding: 10px 16px;
                border: none;
                border-radius: 6px;
            }
            #btnChoosePdf:hover {
                background-color: #1d4ed8;
            }
            #btnChoosePdf:pressed {
                background-color: #1e40af;
            }
            #btnDetectLang {
                background-color: #3b82f6;
                color: #ffffff;
                font-size: 12px;
                font-weight: 500;
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
            }
            #btnDetectLang:hover {
                background-color: #2563eb;
            }
            QComboBox {
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                color: #1e293b;
            }
            QComboBox:hover {
                border-color: #94a3b8;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            #btnTranslate {
                background-color: #6b21a8;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 11px 16px;
                border: none;
                border-radius: 6px;
            }
            #btnTranslate:hover {
                background-color: #581c87;
            }
            #btnTranslate:pressed {
                background-color: #3b0764;
            }
            #btnTranslate:disabled {
                background-color: #d8b4fe;
                color: #ffffff;
            }
            #btnSave {
                background-color: #7e22ce;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 11px 16px;
                border: none;
                border-radius: 6px;
            }
            #btnSave:hover {
                background-color: #6b21a8;
            }
            #btnSave:pressed {
                background-color: #4c1d95;
            }
            #btnSave:disabled {
                background-color: #e9d5ff;
                color: #ffffff;
            }
            #btnCancel {
                background-color: #ef4444;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
            }
            #btnCancel:hover {
                background-color: #dc2626;
            }
            #lblFileInfo {
                color: #475569;
                font-size: 11px;
                background-color: #f1f5f9;
                padding: 6px 8px;
                border-radius: 4px;
            }
            #lblStatus {
                color: #334155;
                font-size: 12px;
            }
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                text-align: center;
                height: 18px;
                font-size: 11px;
                font-weight: bold;
                color: #1e293b;
                background-color: #f1f5f9;
            }
            QProgressBar::chunk {
                background-color: #9333ea;
                border-radius: 5px;
            }
            QCheckBox {
                color: #1e293b;
                font-size: 11px;
                font-weight: 500;
                spacing: 7px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background-color: #f8fafc;
            }
            QCheckBox::indicator:hover {
                border-color: #9333ea;
            }
            QCheckBox::indicator:checked {
                background-color: #9333ea;
                border-color: #7e22ce;
            }
        """)

    def _choose_pdf_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choisir un fichier PDF",
            "",
            "Documents PDF (*.pdf)"
        )
        if not file_path:
            return

        try:
            doc = fitz.open(file_path)
            self.source_doc = doc
            self.source_pdf_path = file_path
            total_pages = len(doc)

            file_name = os.path.basename(file_path)
            self.lbl_file_info.setText(f"📄 {file_name}\n({total_pages} page{'s' if total_pages > 1 else ''})")

            # Update previews
            self.dual_viewer.set_source_document(self.source_doc)
            self.dual_viewer.set_translated_document(None)

            self.btn_translate.setEnabled(True)
            self.btn_save.setEnabled(False)
            self.lbl_status.setText("Document prêt à être traduit.")

            # Automatically run language detection on load
            self._detect_source_language()

        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'ouvrir le fichier PDF :\n{e}")

    def _detect_source_language(self):
        if not self.source_doc:
            QMessageBox.information(self, "Information", "Veuillez d'abord choisir un fichier PDF.")
            return

        sample_text = PdfProcessor.extract_sample_text_for_detection(self.source_doc)
        if not sample_text:
            self.lbl_status.setText("Impossible d'extraire du texte pour la détection.")
            return

        detected_code = self.translator_engine.detect_language(sample_text)
        idx = self.combo_source_lang.findData(detected_code)
        if idx >= 0:
            self.combo_source_lang.setCurrentIndex(idx)
            lang_name = LANGUAGE_CODE_TO_NAME.get(detected_code, detected_code)
            self.lbl_status.setText(f"Langue détectée : {lang_name}")
        else:
            self.lbl_status.setText(f"Langue détectée : {detected_code} (non listée)")

    def _refresh_language_combos(self):
        """
        Populates language dropdowns and indicates which models are available offline.
        """
        installed = self.translator_engine.get_installed_language_codes()
        src_cur = self.combo_source_lang.currentData() if hasattr(self, 'combo_source_lang') and self.combo_source_lang.count() > 0 else "en"
        tgt_cur = self.combo_target_lang.currentData() if hasattr(self, 'combo_target_lang') and self.combo_target_lang.count() > 0 else "fr"

        self.combo_source_lang.blockSignals(True)
        self.combo_target_lang.blockSignals(True)
        self.combo_source_lang.clear()
        self.combo_target_lang.clear()

        for code, name in SUPPORTED_LANGUAGES:
            status = " [Hors-ligne OK]" if code in installed else ""
            self.combo_source_lang.addItem(f"{name}{status}", code)
            self.combo_target_lang.addItem(f"{name}{status}", code)

        s_idx = self.combo_source_lang.findData(src_cur)
        if s_idx >= 0:
            self.combo_source_lang.setCurrentIndex(s_idx)
        else:
            self.combo_source_lang.setCurrentIndex(0)

        t_idx = self.combo_target_lang.findData(tgt_cur)
        if t_idx >= 0:
            self.combo_target_lang.setCurrentIndex(t_idx)
        else:
            fr_idx = self.combo_target_lang.findData("fr")
            if fr_idx >= 0:
                self.combo_target_lang.setCurrentIndex(fr_idx)

        self.combo_source_lang.blockSignals(False)
        self.combo_target_lang.blockSignals(False)

    def _start_translation(self):
        if not self.source_pdf_path or not self.source_doc:
            return

        from_code = self.combo_source_lang.currentData()
        to_code = self.combo_target_lang.currentData()

        if from_code == to_code:
            QMessageBox.warning(self, "Attention", "La langue source et la langue cible sont identiques.")
            return

        # Prepare temporary output path
        output_dir = os.path.join(os.path.dirname(self.source_pdf_path), "traduit")
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(self.source_pdf_path))[0]
        self.translated_pdf_path = os.path.join(output_dir, f"{base_name}_{to_code}.pdf")

        # Disable buttons during translation
        self.btn_choose_pdf.setEnabled(False)
        self.btn_translate.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_detect_lang.setEnabled(False)
        self.combo_source_lang.setEnabled(False)
        self.combo_target_lang.setEnabled(False)
        self.chk_skip_figures.setEnabled(False)

        self.btn_cancel.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Initialisation de la traduction...")

        # Start background worker
        self.worker = TranslationWorker(
            input_path=self.source_pdf_path,
            output_path=self.translated_pdf_path,
            from_lang=from_code,
            to_lang=to_code,
            translator_func=self.translator_engine.translate_batch_texts,
            engine=self.translator_engine,
            skip_figures=self.chk_skip_figures.isChecked()
        )
        self.worker.progress_signal.connect(self._on_translation_progress)
        self.worker.finished_signal.connect(self._on_translation_finished)
        self.worker.start()

    def _on_translation_progress(self, cur_page: int, total_pages: int, msg: str):
        if total_pages > 0:
            percent = int((cur_page / total_pages) * 100)
            self.progress_bar.setValue(percent)
        self.lbl_status.setText(msg)

    def _on_translation_finished(self, success: bool, output_path: str, err_msg: str):
        self.btn_choose_pdf.setEnabled(True)
        self.btn_translate.setEnabled(True)
        self.btn_detect_lang.setEnabled(True)
        self.combo_source_lang.setEnabled(True)
        self.combo_target_lang.setEnabled(True)
        self.chk_skip_figures.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.progress_bar.setVisible(False)
        self._refresh_language_combos()

        if success and output_path and os.path.exists(output_path):
            self.lbl_status.setText("Traduction terminée avec succès !")
            try:
                self.translated_doc = fitz.open(output_path)
                self.dual_viewer.set_translated_document(self.translated_doc)
                self.btn_save.setEnabled(True)
                QMessageBox.information(
                    self,
                    "Succès",
                    "Le document a été traduit avec succès tout en conservant la mise en page, les graphiques et les images !"
                )
            except Exception as e:
                QMessageBox.warning(self, "Avertissement", f"Erreur lors de l'affichage du PDF traduit :\n{e}")
        else:
            self.lbl_status.setText("Traduction échouée ou annulée.")
            if err_msg:
                QMessageBox.critical(self, "Erreur de traduction", f"Détails :\n{err_msg}")

    def _cancel_translation(self):
        if self.worker and self.worker.isRunning():
            self.lbl_status.setText("Annulation en cours...")
            self.worker.cancel()

    def _save_translated_pdf(self):
        if not self.translated_pdf_path or not os.path.exists(self.translated_pdf_path):
            QMessageBox.warning(self, "Attention", "Aucun PDF traduit n'est disponible pour l'enregistrement.")
            return

        to_code = self.combo_target_lang.currentData()
        suggested_name = f"traduit_{to_code}.pdf"
        if self.source_pdf_path:
            base = os.path.splitext(os.path.basename(self.source_pdf_path))[0]
            suggested_name = f"{base}_{to_code}.pdf"

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le fichier PDF traduit",
            suggested_name,
            "Documents PDF (*.pdf)"
        )
        if not dest_path:
            return

        try:
            shutil.copy2(self.translated_pdf_path, dest_path)
            self.lbl_status.setText(f"Enregistré : {os.path.basename(dest_path)}")
            QMessageBox.information(
                self,
                "Enregistré",
                f"Le fichier PDF traduit a été enregistré avec succès :\n{dest_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Échec de l'enregistrement :\n{e}")
