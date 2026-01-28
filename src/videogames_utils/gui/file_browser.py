"""
File browser widget for selecting replays
"""

from pathlib import Path
from typing import Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QTreeWidget, QTreeWidgetItem, QPushButton, QGroupBox, QFileDialog
)
from PyQt6.QtCore import pyqtSignal

from .utils import get_replay_info, detect_game_from_filename, get_replays_from_events_files


class FileBrowser(QWidget):
    """Widget for browsing and selecting replays from datasets"""

    replay_selected = pyqtSignal(object)  # Emits replay info dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dataset = None
        self.replays = []
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()

        # Dataset selection
        dataset_group = QGroupBox("Dataset Selection")
        dataset_layout = QVBoxLayout()

        self.browse_button = QPushButton("Browse for Dataset...")
        self.browse_button.clicked.connect(self.browse_for_dataset)
        dataset_layout.addWidget(self.browse_button)

        self.dataset_label = QLabel("No dataset loaded")
        self.dataset_label.setWordWrap(True)
        dataset_layout.addWidget(self.dataset_label)

        dataset_group.setLayout(dataset_layout)
        layout.addWidget(dataset_group)

        # Filter controls
        filter_group = QGroupBox("Filters")
        filter_layout = QHBoxLayout()

        self.subject_combo = QComboBox()
        self.subject_combo.addItem("All Subjects")
        self.subject_combo.currentTextChanged.connect(self.update_replay_tree)

        self.session_combo = QComboBox()
        self.session_combo.addItem("All Sessions")
        self.session_combo.currentTextChanged.connect(self.update_replay_tree)

        self.level_combo = QComboBox()
        self.level_combo.addItem("All Levels")
        self.level_combo.currentTextChanged.connect(self.update_replay_tree)

        filter_layout.addWidget(QLabel("Subject:"))
        filter_layout.addWidget(self.subject_combo)
        filter_layout.addWidget(QLabel("Session:"))
        filter_layout.addWidget(self.session_combo)
        filter_layout.addWidget(QLabel("Level:"))
        filter_layout.addWidget(self.level_combo)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # Replay tree
        replay_group = QGroupBox("Replays")
        replay_layout = QVBoxLayout()

        self.replay_tree = QTreeWidget()
        self.replay_tree.setHeaderLabels(["Subject", "Session", "Level", "Rep"])
        self.replay_tree.itemDoubleClicked.connect(self.on_replay_selected)

        replay_layout.addWidget(self.replay_tree)

        # Load button
        self.load_button = QPushButton("Load Selected Replay")
        self.load_button.clicked.connect(self.on_load_button_clicked)
        self.load_button.setEnabled(False)
        replay_layout.addWidget(self.load_button)

        replay_group.setLayout(replay_layout)
        layout.addWidget(replay_group)

        self.setLayout(layout)

    def browse_for_dataset(self):
        """Open file dialog to select a dataset directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Dataset Directory",
            str(Path.home() / "DATA" / "neuromod" / "vg_data"),
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            dataset_path = Path(directory)
            self.load_dataset(dataset_path)

    def load_dataset(self, dataset_path: Path):
        """Load a specific dataset"""
        self.current_dataset = dataset_path
        self.dataset_label.setText(f"Dataset: {dataset_path.name}\n{str(dataset_path)}")

        self.load_replays()
        self.update_filters()
        self.update_replay_tree()

    def load_replays(self):
        """Load all replays from the current dataset"""
        if self.current_dataset is None:
            return

        self.replays = []

        # Try to load from events files first (more reliable, includes skip_first_step info)
        try:
            self.replays = get_replays_from_events_files(self.current_dataset)
            print(f"Loaded {len(self.replays)} replays from events files")
        except Exception as e:
            print(f"Warning: Could not load from events files: {e}")

        # Fallback: glob for bk2 files if events parsing failed
        if not self.replays:
            print("Falling back to bk2 file globbing...")
            bk2_files = list(self.current_dataset.rglob("**/*.bk2"))

            for bk2_file in bk2_files:
                try:
                    info = get_replay_info(bk2_file)
                    info['skip_first_step'] = False  # Unknown without events file
                    self.replays.append(info)
                except Exception as e:
                    print(f"Error loading {bk2_file}: {e}")

        # Sort by subject, session, level, repetition
        self.replays.sort(key=lambda r: (r['subject'], r['session'], r['level'], r['rep']))

    def update_filters(self):
        """Update subject, session, and level filter dropdowns"""
        subjects = sorted(set(r['subject'] for r in self.replays))
        sessions = sorted(set(r['session'] for r in self.replays))
        levels = sorted(set(r['level'] for r in self.replays))

        # Update subject combo
        current_subject = self.subject_combo.currentText()
        self.subject_combo.clear()
        self.subject_combo.addItem("All Subjects")
        self.subject_combo.addItems(subjects)
        if current_subject in subjects:
            self.subject_combo.setCurrentText(current_subject)

        # Update session combo
        current_session = self.session_combo.currentText()
        self.session_combo.clear()
        self.session_combo.addItem("All Sessions")
        self.session_combo.addItems(sessions)
        if current_session in sessions:
            self.session_combo.setCurrentText(current_session)

        # Update level combo
        current_level = self.level_combo.currentText()
        self.level_combo.clear()
        self.level_combo.addItem("All Levels")
        self.level_combo.addItems(levels)
        if current_level in levels:
            self.level_combo.setCurrentText(current_level)

    def update_replay_tree(self):
        """Update the replay tree with filtered replays"""
        self.replay_tree.clear()

        subject_filter = self.subject_combo.currentText()
        session_filter = self.session_combo.currentText()
        level_filter = self.level_combo.currentText()

        filtered_replays = self.replays

        if subject_filter != "All Subjects":
            filtered_replays = [r for r in filtered_replays if r['subject'] == subject_filter]

        if session_filter != "All Sessions":
            filtered_replays = [r for r in filtered_replays if r['session'] == session_filter]

        if level_filter != "All Levels":
            filtered_replays = [r for r in filtered_replays if r['level'] == level_filter]

        # Add to tree
        for replay in filtered_replays:
            item = QTreeWidgetItem([
                replay['subject'],
                replay['session'],
                replay['level'],
                replay['rep']
            ])
            item.setData(0, 1, replay)  # Store replay info in item
            self.replay_tree.addTopLevelItem(item)

        self.replay_tree.resizeColumnToContents(0)
        self.replay_tree.resizeColumnToContents(1)
        self.replay_tree.resizeColumnToContents(2)
        self.replay_tree.setColumnWidth(3, 50)  # Rep column: narrow fixed width

    def on_replay_selected(self, item: QTreeWidgetItem, column: int):
        """Handle double-click on replay item"""
        self.load_button.setEnabled(True)

    def on_load_button_clicked(self):
        """Handle load button click"""
        current_item = self.replay_tree.currentItem()
        if current_item is None:
            return

        replay_info = current_item.data(0, 1)
        if replay_info:
            # Add dataset path to replay info
            replay_info['dataset_path'] = self.current_dataset
            self.replay_selected.emit(replay_info)

    def get_selected_replay(self) -> Optional[dict]:
        """Get the currently selected replay info"""
        current_item = self.replay_tree.currentItem()
        if current_item is None:
            return None

        replay_info = current_item.data(0, 1)
        if replay_info:
            replay_info['dataset_path'] = self.current_dataset
        return replay_info
