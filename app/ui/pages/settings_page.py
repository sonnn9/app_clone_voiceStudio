"""Settings page: connection, output, processing, appearance."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.api.models import HealthInfo
from app.audio.ffmpeg import ffmpeg_version
from app.ui import theme
from app.ui.context import AppContext
from app.ui.pages.logs_page import open_path
from app.ui.widgets import StatusDot, muted, page_header, primary
from app.ui.workers import run_async
from app.utils.paths import app_data_dir


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.addWidget(page_header("Settings"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        s = ctx.settings

        # ---- connection
        g = QGroupBox("AudioStudio server")
        f = QFormLayout(g)
        url_row = QHBoxLayout()
        self.url = QLineEdit(s.api_base_url)
        self.url.setPlaceholderText("http://127.0.0.1:<port>")
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setToolTip("Try the candidate addresses listed in default_settings.json")
        self.test_btn = primary("Test Connection")
        url_row.addWidget(self.url, 1)
        url_row.addWidget(self.detect_btn)
        url_row.addWidget(self.test_btn)
        f.addRow("API Base URL", url_row)
        st_row = QHBoxLayout()
        self.dot = StatusDot()
        self.state = QLabel("Not tested")
        st_row.addWidget(self.dot)
        st_row.addWidget(self.state, 1)
        f.addRow("Status", st_row)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(self.info.textInteractionFlags())
        f.addRow("Server info", self.info)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(s.timeout_s))
        self.timeout.setToolTip("Maximum time for one generation request.")
        self.retries = QSpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(s.retry_count)
        self.delays = QLineEdit(", ".join(f"{d:g}" for d in s.retry_delays_s))
        self.delays.setToolTip("Seconds to wait before retry 1, 2, 3 … (increasing). GPU out-of-memory "
                               "errors are not retried.")
        f.addRow("Timeout", self.timeout)
        f.addRow("Retry count", self.retries)
        f.addRow("Retry delays (s)", self.delays)
        lay.addWidget(g)

        # ---- output
        g2 = QGroupBox("Output")
        f2 = QFormLayout(g2)
        self.fmt = QComboBox()
        for fmt in ("mp3", "wav", "flac"):
            self.fmt.addItem(fmt.upper(), fmt)
        self.fmt.setCurrentIndex(self.fmt.findData(s.output_format))
        self.bitrate = QComboBox()
        for b in (128, 192, 256, 320):
            self.bitrate.addItem(f"{b} kbps", b)
        self.bitrate.setCurrentIndex(self.bitrate.findData(s.mp3_bitrate_kbps))
        self.bitrate.setToolTip("AudioStudio returns lossless WAV; MP3 is encoded locally at this bitrate.\n"
                                "Note: for 24 kHz voices the MP3 standard allows at most 160 kbps, "
                                "so higher settings are encoded at 160 kbps.")
        self.normalize = QCheckBox("Normalize output volume (gentle EBU R128, no compression)")
        self.normalize.setChecked(s.normalize_volume)
        self.metadata = QCheckBox("Write tags (Title = TXT name, Comment = generator)")
        self.metadata.setChecked(s.write_metadata)
        ff_row = QHBoxLayout()
        self.ffmpeg = QLineEdit(s.ffmpeg_path)
        self.ffmpeg.setPlaceholderText("auto-detect (next to the app or on PATH)")
        ff_browse = QPushButton("Browse…")
        ff_row.addWidget(self.ffmpeg, 1)
        ff_row.addWidget(ff_browse)
        self.ff_status = muted("")
        f2.addRow("Format", self.fmt)
        f2.addRow("MP3 quality", self.bitrate)
        f2.addRow("", self.normalize)
        f2.addRow("", self.metadata)
        f2.addRow("ffmpeg", ff_row)
        f2.addRow("", self.ff_status)
        lay.addWidget(g2)

        # ---- processing
        g3 = QGroupBox("Processing")
        f3 = QFormLayout(g3)
        self.conc = QComboBox()
        for n in (1, 2, 3, 4):
            self.conc.addItem(str(n), n)
        self.conc.setCurrentIndex(self.conc.findData(s.concurrency))
        self.conc_warn = muted("More concurrent jobs use more GPU memory (VRAM). Keep 1 for local GPU TTS "
                               "unless you know your GPU has room.")
        self.max_chars = QSpinBox()
        self.max_chars.setRange(50, 4096)
        self.max_chars.setValue(s.max_chunk_chars)
        self.max_chars.setToolTip("Longer texts are split into chunks no larger than this. Capped by the "
                                  "server's limit for the engine.")
        self.min_chars = QSpinBox()
        self.min_chars.setRange(0, 1000)
        self.min_chars.setValue(s.min_chunk_chars)
        self.min_chars.setToolTip("Very short chunks are merged with neighbours when possible.")
        self.sentence = QCheckBox("Sentence-aware splitting")
        self.sentence.setChecked(s.sentence_aware)
        self.cache = QCheckBox("Enable audio cache (reuse identical segments)")
        self.cache.setChecked(s.cache_enabled)
        cache_row = QHBoxLayout()
        self.cache_size = muted("")
        clear_cache = QPushButton("Clear Cache")
        cache_row.addWidget(self.cache_size, 1)
        cache_row.addWidget(clear_cache)
        self.folder_cfg = QCheckBox("Use tts_config.json files in folders")
        self.folder_cfg.setChecked(s.use_folder_config)
        self.inherit_cfg = QCheckBox("Subfolders inherit the parent folder's tts_config.json")
        self.inherit_cfg.setChecked(s.inherit_parent_folder_config)
        f3.addRow("Concurrent jobs", self.conc)
        f3.addRow("", self.conc_warn)
        f3.addRow("Max characters per chunk", self.max_chars)
        f3.addRow("Minimum chunk size", self.min_chars)
        f3.addRow("", self.sentence)
        f3.addRow("", self.cache)
        f3.addRow("", cache_row)
        f3.addRow("", self.folder_cfg)
        f3.addRow("", self.inherit_cfg)
        lay.addWidget(g3)

        # ---- preprocessing
        g4 = QGroupBox("Text preprocessing")
        grid = QGridLayout(g4)
        pp = s.preprocess
        self.pp_spaces = QCheckBox("Trim duplicate spaces")
        self.pp_lines = QCheckBox("Normalize line endings")
        self.pp_blank = QCheckBox("Remove extra blank lines")
        self.pp_quotes = QCheckBox("Convert curly quotes to plain quotes")
        self.pp_pron = QCheckBox("Apply pronunciation rules")
        for i, (cb, val) in enumerate(((self.pp_spaces, pp.collapse_spaces), (self.pp_lines, pp.normalize_line_endings),
                                       (self.pp_blank, pp.remove_extra_blank_lines),
                                       (self.pp_quotes, pp.convert_smart_quotes), (self.pp_pron, pp.apply_pronunciation))):
            cb.setChecked(val)
            grid.addWidget(cb, i // 2, i % 2)
        lay.addWidget(g4)

        # ---- appearance & data
        g5 = QGroupBox("Appearance & data")
        f5 = QFormLayout(g5)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.8, 2.0)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(s.ui_scale)
        self.scale.setToolTip("Interface scale (applied after restart).")
        data_row = QHBoxLayout()
        open_data = QPushButton("Open App Data Folder")
        data_row.addWidget(muted(str(app_data_dir())), 1)
        data_row.addWidget(open_data)
        f5.addRow("Theme", self.theme)
        f5.addRow("UI scale", self.scale)
        f5.addRow("App data", data_row)
        lay.addWidget(g5)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = primary("Save settings")
        save_row.addWidget(self.save_btn)
        lay.addLayout(save_row)
        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.test_btn.clicked.connect(self._test)
        self.detect_btn.clicked.connect(self._detect)
        self.save_btn.clicked.connect(self.save)
        ff_browse.clicked.connect(self._browse_ffmpeg)
        clear_cache.clicked.connect(self._clear_cache)
        open_data.clicked.connect(lambda: open_path(app_data_dir()))
        self.theme.currentIndexChanged.connect(self._theme_changed)
        ctx.connection_changed.connect(self.show_health)
        self._update_ffmpeg()
        self._update_cache_size()
        if ctx.health:
            self.show_health(ctx.health)

    # --------------------------------------------------------- connection
    def _test(self) -> None:
        self.state.setText("Testing…")
        self.dot.set_state("warn")
        self._apply_connection_fields()
        self.ctx.apply_connection_settings()

    def _apply_connection_fields(self) -> None:
        s = self.ctx.settings
        s.api_base_url = self.url.text().strip().rstrip("/")
        s.timeout_s = float(self.timeout.value())

    def _detect(self) -> None:
        candidates = list(self.ctx.settings.api_discovery_candidates)
        if not candidates:
            QMessageBox.information(self, "Detect", "No candidate addresses configured.")
            return
        from app.api.audiostudio_adapter import AudioStudioAdapter

        self.state.setText("Detecting…")

        def work():
            for url in candidates:
                h = AudioStudioAdapter(url, 10).connect()
                if h.connected:
                    return url
            return None

        def done(url):
            if url:
                self.url.setText(url)
                self._test()
            else:
                self.state.setText("No AudioStudio server found at: " + ", ".join(candidates))
                self.dot.set_state("danger")

        run_async(work, done)

    def show_health(self, h: HealthInfo) -> None:
        if h.connected:
            self.dot.set_state("ok")
            self.state.setText("<b>Connected</b>")
            lines = [f"Version {h.version}"]
            if h.device:
                lines.append(f"Device: {h.device}")
            if h.gpu_name:
                lines.append(f"GPU: {h.gpu_name} ({h.vram_gb:.1f} GB VRAM)")
            if h.active_engine:
                lines.append(f"Active engine: {h.active_engine}" + (f" ({h.active_model})" if h.active_model else ""))
            if h.model_status:
                lines.append(f"Model status: {h.model_status}")
            lines += [f"{k}: {v}" for k, v in h.details.items()]
            self.info.setText("\n".join(lines))
        else:
            self.dot.set_state("danger")
            self.state.setText("<b>Not Connected</b> – " + (h.message or ""))
            self.info.setText("Start AudioStudio, then check the URL and press Test Connection.")

    # -------------------------------------------------------------- misc
    def _browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg.exe", "", "ffmpeg (ffmpeg.exe ffmpeg);;All files (*)")
        if path:
            self.ffmpeg.setText(path)
            self.ctx.settings.ffmpeg_path = path
            self._update_ffmpeg()

    def _update_ffmpeg(self) -> None:
        found = self.ctx.ffmpeg()
        if found:
            self.ff_status.setText(f"✓ {ffmpeg_version(found) or found}")
        else:
            self.ff_status.setText("✗ ffmpeg not found – MP3/FLAC output is unavailable (WAV still works).")

    def _update_cache_size(self) -> None:
        def done(size):
            self.cache_size.setText(f"Cache size: {size / 1_048_576:.1f} MB")

        run_async(self.ctx.batch.cache.size_bytes, done)

    def _clear_cache(self) -> None:
        if QMessageBox.question(self, "Clear cache", "Delete all cached audio segments?") == QMessageBox.StandardButton.Yes:
            self.ctx.batch.cache.clear()
            self._update_cache_size()

    def _theme_changed(self) -> None:
        self.ctx.settings.theme = self.theme.currentData()
        theme.apply_theme(QApplication.instance(), self.ctx.settings.theme)
        self.ctx.save_settings()

    def save(self) -> None:
        s = self.ctx.settings
        old_url, old_timeout = s.api_base_url, s.timeout_s
        self._apply_connection_fields()
        s.retry_count = self.retries.value()
        try:
            delays = [float(x) for x in self.delays.text().replace(";", ",").split(",") if x.strip()]
            s.retry_delays_s = delays or [1.0, 3.0, 5.0]
        except ValueError:
            QMessageBox.warning(self, "Settings", "Retry delays must be numbers separated by commas.")
            return
        s.output_format = self.fmt.currentData()
        s.mp3_bitrate_kbps = self.bitrate.currentData()
        s.normalize_volume = self.normalize.isChecked()
        s.write_metadata = self.metadata.isChecked()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        s.concurrency = self.conc.currentData()
        s.max_chunk_chars = self.max_chars.value()
        s.min_chunk_chars = self.min_chars.value()
        s.sentence_aware = self.sentence.isChecked()
        s.cache_enabled = self.cache.isChecked()
        s.use_folder_config = self.folder_cfg.isChecked()
        s.inherit_parent_folder_config = self.inherit_cfg.isChecked()
        pp = s.preprocess
        pp.collapse_spaces = self.pp_spaces.isChecked()
        pp.normalize_line_endings = self.pp_lines.isChecked()
        pp.remove_extra_blank_lines = self.pp_blank.isChecked()
        pp.convert_smart_quotes = self.pp_quotes.isChecked()
        pp.apply_pronunciation = self.pp_pron.isChecked()
        s.ui_scale = round(self.scale.value(), 2)
        if s.concurrency > 1:
            QMessageBox.information(self, "Concurrency",
                                    f"{s.concurrency} concurrent jobs will run at once. This increases GPU memory "
                                    "use; if you see out-of-memory errors, go back to 1.")
        if (s.api_base_url, s.timeout_s) != (old_url, old_timeout):
            self.ctx.apply_connection_settings()
        else:
            self.ctx.save_settings()
        self._update_ffmpeg()
        self.state.setText(self.state.text())
