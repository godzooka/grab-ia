#!/usr/bin/env python3
import sys
import csv
from pathlib import Path
from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QFileDialog, QLabel, QPushButton,
    QCheckBox, QLineEdit, QTextEdit,
    QProgressBar, QComboBox, QSpinBox,
    QHBoxLayout, QVBoxLayout, QGridLayout,
    QFrame
)
from PySide6.QtGui import QTextCursor

from grabia_core import GrabIACore


# =========================
# LOG BUFFER (BOUNDED)
# =========================
class LogBuffer:
    def __init__(self, max_lines=8000):
        self.lines = deque(maxlen=max_lines)

    def append(self, line):
        self.lines.append(line)

    def filtered(self, level):
        if level == "ALL":
            return list(self.lines)
        return [l for l in self.lines if f"[{level}]" in l]


# =========================
# MAIN WINDOW
# =========================
class GrabIAGUI(QMainWindow):

    DISPLAY_NAMES = {
        "queue_depth": "Queue",
        "failed_files": "Failed",
        "current_speed_mbps": "Speed",
        "active_threads": "Active",
        "total_files": "Total Files",
        "items_done": "Completed",
        "scanned_ids": "Items Scanned",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("grab-IA   |   Internet Archive Downloader")
        self.resize(1400, 900)

        self.core = None
        self.identifiers = []
        self.log_index = 0
        self.log_buffer = LogBuffer()
        self.job_finished = False

        self._build_ui()
        self._apply_theme()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_core)

    # =========================
    # UI
    # =========================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # -------- Header metrics --------
        self.metric_labels = {}
        header = QHBoxLayout()
        for key in [
            "queue_depth", "failed_files",
            "current_speed_mbps", "active_threads",
            "total_files", "items_done", "scanned_ids"
        ]:
            title = self.DISPLAY_NAMES.get(key, key)
            lbl = QLabel(f"{title}: 0")
            lbl.setToolTip({
                "queue_depth": "Number of files currently waiting in the download queue",
                "failed_files": "Files that failed to download",
                "current_speed_mbps": "Current aggregate download speed",
                "active_threads": "Workers actively downloading files",
                "total_files": "Total files discovered for all items",
                "items_done": "Files successfully completed",
                "scanned_ids": "Item identifiers scanned so far",
            }.get(key, key))
            lbl.setFrameStyle(QFrame.Panel | QFrame.Raised)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumWidth(140)
            header.addWidget(lbl)
            self.metric_labels[key] = lbl
        root.addLayout(header)

        # -------- Body --------
        body = QHBoxLayout()
        root.addLayout(body, 1)

        # -------- Sidebar --------
        sidebar_widget = QWidget()
        sidebar_widget.setMaximumWidth(380)
        sidebar_widget.setMinimumWidth(360)

        sidebar = QGridLayout(sidebar_widget)
        sidebar.setContentsMargins(6, 6, 6, 6)
        sidebar.setVerticalSpacing(6)

        r = 0

        def add(label, widget):
            nonlocal r
            sidebar.addWidget(QLabel(label), r, 0)
            sidebar.addWidget(widget, r, 1)
            r += 1

        # Item list
        self.item_path = QLineEdit()
        self.item_path.setToolTip(
            "Path to a TXT or CSV file containing Internet Archive item identifiers."
        )

        btn_items = QPushButton("Browse")
        btn_items.setToolTip(
            "Select a text or CSV file containing item identifiers."
        )
        btn_items.clicked.connect(self.load_items)
        sidebar.addWidget(QLabel("Item list (TXT/CSV)"), r, 0)
        sidebar.addWidget(self.item_path, r, 1)
        sidebar.addWidget(btn_items, r, 2)
        r += 1

        # Output dir
        self.output_dir = QLineEdit()
        self.output_dir.setToolTip(
            "Directory where downloaded files will be stored."
        )

        btn_out = QPushButton("Browse")
        btn_out.setToolTip(
            "Select the output directory for downloads."
        )
        btn_out.clicked.connect(self.select_output)
        sidebar.addWidget(QLabel("Output directory"), r, 0)
        sidebar.addWidget(self.output_dir, r, 1)
        sidebar.addWidget(btn_out, r, 2)
        r += 1

        # Auth/env
        self.auth_path = QLineEdit()
        self.auth_path.setToolTip(
            "Path to a .env or credentials file containing Internet Archive authentication variables."
        )
        add("Auth / env path", self.auth_path)

        # Filters
        self.filter_regex = QLineEdit()
        self.filter_regex.setToolTip(
            "Regular expression used to include only matching filenames."
        )
        add("Filename regex", self.filter_regex)


        self.extension_whitelist = QLineEdit()
        self.extension_whitelist.setToolTip(
            "Comma-separated list of file extensions to include (e.g. mp4,pdf,jpg). Leave empty for all files."
        )
        add("Extensions (comma-separated)", self.extension_whitelist)

        # Modes
        self.chk_metadata = QCheckBox("Metadata only")
        self.chk_metadata.setToolTip(
            "Download metadata files only, without media content."
        )


        self.chk_sync = QCheckBox("Sync mode")
        self.chk_sync.setToolTip(
            "Skip files that already exist locally and match size."
        )

        self.chk_dynamic = QCheckBox("Dynamic scaling")
        self.chk_dynamic.setToolTip(
            "Automatically adjust worker count based on workload."
        )

        sidebar.addWidget(self.chk_metadata, r, 0, 1, 2); r += 1
        sidebar.addWidget(self.chk_sync, r, 0, 1, 2); r += 1
        sidebar.addWidget(self.chk_dynamic, r, 0, 1, 2); r += 1

        # Performance
        self.max_workers = QSpinBox()
        self.max_workers.setRange(1, 64)
        self.max_workers.setValue(8)
        self.max_workers.setToolTip(
            "Maximum number of concurrent download workers."
        )
        add("Max workers", self.max_workers)

        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 2_147_483_647)
        self.speed_limit.setToolTip(
            "Optional bandwidth limit in megabytes per second (0 = unlimited)."
        )
        add("Speed limit (MB/s)", self.speed_limit)


    
        # Controls
        self.btn_start = QPushButton("START")
        self.btn_start.setToolTip(
            "Start the download job using the current settings."
        )

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setToolTip(
            "Stop the running job safely."
        )

        sidebar.addWidget(self.btn_start, r, 0, 1, 3); r += 1
        sidebar.addWidget(self.btn_stop, r, 0, 1, 3); r += 1

        self.btn_start.clicked.connect(self.start_job)
        self.btn_stop.clicked.connect(self.stop_job)

        body.addWidget(sidebar_widget, 0)

        # -------- Log --------
        log_layout = QVBoxLayout()
        body.addLayout(log_layout, 1)

        self.severity_filter = QComboBox()
        self.severity_filter.addItems(
            ["ALL", "ERROR", "WARNING", "INFO", "SUCCESS"]
        )
        self.severity_filter.setToolTip(
            "Filter log messages by severity level."
        )
        self.severity_filter.currentTextChanged.connect(self.refresh_log_view)
        log_layout.addWidget(self.severity_filter)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setToolTip(
            "Activity Log."
        )
        log_layout.addWidget(self.log_view, 1)

        # -------- Footer --------
        self.progress = QProgressBar()
        root.addWidget(self.progress)

        self.worker_bars = []
        self.worker_container = QVBoxLayout()
        root.addLayout(self.worker_container)

    # =========================
    # CORE CONTROL
    # =========================
    def load_items(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select item list", "", "Text/CSV (*.txt *.csv)"
        )
        if not path:
            return
        self.item_path.setText(path)
        self.identifiers.clear()
        p = Path(path)
        if p.suffix.lower() == ".csv":
            with open(p) as f:
                for row in csv.reader(f):
                    if row:
                        self.identifiers.append(row[0].strip())
        else:
            self.identifiers = [
                l.strip() for l in p.read_text().splitlines() if l.strip()
            ]

    def select_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.output_dir.setText(d)

    def start_job(self):
        self.job_finished = False
        self.log_view.clear()
        self.log_buffer = LogBuffer()
        self.log_index = 0

        self.core = GrabIACore(
            output_dir=self.output_dir.text(),
            max_workers=self.max_workers.value(),
            speed_limit_bps=self.speed_limit.value() * 1024 * 1024,
            sync_mode=self.chk_sync.isChecked(),
            filter_regex=self.filter_regex.text() or None,
            extension_whitelist=[
                e.strip() for e in self.extension_whitelist.text().split(",")
                if e.strip()
            ] or None,
            dynamic_scaling=self.chk_dynamic.isChecked(),
            metadata_only=self.chk_metadata.isChecked()
        )

        self.core.start(self.identifiers)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.poll_timer.start(250)

    def stop_job(self):
        if self.core:
            self.core.stop()

    # =========================
    # POLLING
    # =========================
    def poll_core(self):
        if not self.core:
            return

        stats = self.core.get_stats()
        speed_mbps = stats.get("current_speed_mbps", 0.0)
        speed_mbs = speed_mbps / 8.0  # convert megabits → megabytes
            

        for k, lbl in self.metric_labels.items():
            title = self.DISPLAY_NAMES.get(k, k)

            if k == "current_speed_mbps":
                lbl.setText(f"{title}: {speed_mbs:.1f} MB/s")
            else:
                lbl.setText(f"{title}: {stats.get(k, 0)}")

        self.progress.setValue(int(stats.get("job_percent_complete", 0)))

        logs, self.log_index = self.core.get_logs(self.log_index)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)

        for line in logs:
            self.log_buffer.append(line)
            if (
                self.severity_filter.currentText() == "ALL"
                or f"[{self.severity_filter.currentText()}]" in line
            ):
                cursor.insertText(line + "\n")

        self.log_view.setTextCursor(cursor)

        # ---- Job finished detection ----
        if (
            not self.job_finished
            and not stats["scanner_active"]
            and stats["queue_depth"] == 0
            and stats["items_done"] + stats["failed_files"] >= stats["total_files"]
            and stats["total_files"] > 0
        ):
            self.job_finished = True

            self.progress.setValue(100)  # <-- FORCE 100%

            cursor.insertText(
                "\n=== JOB FINISHED ===\n"
                f"Items scanned: {stats['scanned_ids']}\n"
                f"Files total: {stats['total_files']}\n"
                f"Failed files: {stats['failed_files']}\n"
            )

            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.poll_timer.stop()
    def refresh_log_view(self):
        self.log_view.clear()
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)

        level = self.severity_filter.currentText()
        for line in self.log_buffer.filtered(level):
            cursor.insertText(line + "\n")

        self.log_view.setTextCursor(cursor)

    def closeEvent(self, event):
        """
        Ensure background threads shut down cleanly when the GUI closes.
        """
        try:
            if self.poll_timer.isActive():
                self.poll_timer.stop()

            if self.core:
                self.core.stop()
                self.core = None
        except Exception:
            pass

        event.accept()



    # =========================
    # THEME
    # =========================
    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #3b2f2f;
                color: #ffffff;
                font-family: Ubuntu;
            }
            QTextEdit {
                background-color: #2a201b;
            }
            QPushButton {
                background-color: #e95420;
                padding: 6px;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #e95420;
            }
        """)


# =========================
# ENTRY
# =========================
def main():
    app = QApplication(sys.argv)
    win = GrabIAGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

