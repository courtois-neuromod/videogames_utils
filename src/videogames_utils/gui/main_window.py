"""
Main window for the Video Game Replay Visualizer
"""

from pathlib import Path
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QStatusBar, QMenuBar, QMenu, QFileDialog, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from .file_browser import FileBrowser
from .video_player import VideoPlayer
from .timeseries_widget import TimeseriesWidget
from .events_widget import EventsWidget
from .utils import detect_game_from_filename, find_annotated_events_for_replay


class ReplayVisualizerApp(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.current_replay_info = None
        self.current_dataset_path = None
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Video Game Replay Visualizer")
        self.setGeometry(100, 100, 1200, 700)
        self.setMinimumSize(800, 600)

        # Create menu bar
        self.create_menu_bar()

        # Create main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()

        # Left panel: File browser
        self.file_browser = FileBrowser()
        self.file_browser.replay_selected.connect(self.on_replay_selected)
        self.file_browser.setMaximumWidth(280)
        main_layout.addWidget(self.file_browser)

        # Right panel: Video and visualizations
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: Video player
        self.video_player = VideoPlayer()
        self.video_player.frame_changed.connect(self.on_frame_changed)
        right_splitter.addWidget(self.video_player)

        # Middle: Events
        self.events_widget = EventsWidget()
        right_splitter.addWidget(self.events_widget)

        # Bottom: Timeseries
        self.timeseries_widget = TimeseriesWidget()
        right_splitter.addWidget(self.timeseries_widget)

        # Set initial sizes (video larger, events small, timeseries medium)
        right_splitter.setSizes([400, 100, 400])

        main_layout.addWidget(right_splitter)

        central_widget.setLayout(main_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready - Click 'Browse for Dataset...' to begin")

    def create_menu_bar(self):
        """Create the menu bar"""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("File")

        open_action = QAction("Open Dataset...", self)
        open_action.triggered.connect(self.open_dataset)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menu_bar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def open_dataset(self):
        """Open a dataset directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Dataset Directory",
            str(Path.home() / "DATA" / "neuromod" / "vg_data"),
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            self.file_browser.load_dataset(Path(directory))
            self.status_bar.showMessage(f"Opened: {directory}")

    def on_replay_selected(self, replay_info: Dict):
        """Handle replay selection"""
        self.status_bar.showMessage(f"Loading replay: {replay_info['filename']}")

        self.current_replay_info = replay_info
        self.current_dataset_path = replay_info['dataset_path']

        # Load video
        try:
            self.video_player.load_replay(replay_info, self.current_dataset_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Loading Replay",
                f"Failed to load replay:\n{e}"
            )
            return

        # Load variables
        variables_path = replay_info['path'].parent / (replay_info['path'].stem + '_variables.json')
        if variables_path.exists():
            try:
                self.timeseries_widget.load_variables(variables_path, fps=60)
                self.status_bar.showMessage("Variables loaded")
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to load variables:\n{e}"
                )
        else:
            QMessageBox.warning(
                self,
                "Warning",
                f"Variables file not found:\n{variables_path}"
            )

        # Load events
        # Use events_file from replay_info if available, otherwise search for it
        events_path = replay_info.get('events_file')
        if not events_path:
            events_path = self.find_annotated_events(replay_info)

        if events_path and events_path.exists():
            try:
                self.events_widget.load_events(events_path, replay_info['filename'], fps=60)
                self.status_bar.showMessage("Events loaded")
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to load events:\n{e}"
                )
                import traceback
                traceback.print_exc()
        else:
            self.events_widget.status_label.setText("No annotated events found")

        self.status_bar.showMessage("Replay loaded successfully")

    def find_annotated_events(self, replay_info: Dict) -> Optional[Path]:
        """
        Find the desc-annotated_events.tsv file for a replay

        Looks in the func/ directory for the corresponding session
        """
        return find_annotated_events_for_replay(
            replay_info['dataset_path'],
            replay_info['subject'],
            replay_info['session'],
            replay_info['task']
        )

    def on_frame_changed(self, frame_idx: int):
        """Handle frame change from video player"""
        # Update timeseries position
        self.timeseries_widget.update_position(frame_idx)

        # Update events
        self.events_widget.update_position(frame_idx)

        # Update status bar
        time_seconds = frame_idx / 60.0  # Assuming 60 FPS
        self.status_bar.showMessage(f"Frame: {frame_idx} | Time: {time_seconds:.2f}s")

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About VG Replay Visualizer",
            "Video Game Replay Visualizer\n\n"
            "Interactive tool for exploring CNeuroMod videogame datasets\n\n"
            "Features:\n"
            "- Replay .bk2 game recordings\n"
            "- Display game state variables as timeseries\n"
            "- Show annotated events\n"
            "- Synchronized playback controls\n\n"
            "Part of the videogames_utils toolbox"
        )
