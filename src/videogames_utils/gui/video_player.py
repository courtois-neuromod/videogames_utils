"""
Video player widget for .bk2 replay playback
"""

from pathlib import Path
from typing import Optional, Dict
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QElapsedTimer
from PyQt6.QtGui import QImage, QPixmap, QResizeEvent


class AspectRatioLabel(QLabel):
    """QLabel that maintains aspect ratio"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.aspect_ratio = 256.0 / 240.0  # NES aspect ratio
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def setPixmap(self, pixmap):
        """Override setPixmap to store original and scale properly"""
        self._pixmap = pixmap
        if pixmap:
            self.aspect_ratio = pixmap.width() / pixmap.height()
        super().setPixmap(self._scale_pixmap())

    def _scale_pixmap(self):
        """Scale pixmap to fit while maintaining aspect ratio"""
        if not hasattr(self, '_pixmap') or self._pixmap is None:
            return QPixmap()

        label_width = self.width()
        label_height = self.height()

        # Calculate scaled size maintaining aspect ratio
        if label_width / label_height > self.aspect_ratio:
            # Label is wider than image aspect ratio, fit to height
            scaled_height = label_height
            scaled_width = int(scaled_height * self.aspect_ratio)
        else:
            # Label is taller than image aspect ratio, fit to width
            scaled_width = label_width
            scaled_height = int(scaled_width / self.aspect_ratio)

        return self._pixmap.scaled(
            scaled_width, scaled_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    def resizeEvent(self, event):
        """Handle resize to rescale pixmap"""
        super().resizeEvent(event)
        if hasattr(self, '_pixmap') and self._pixmap is not None:
            super(AspectRatioLabel, self).setPixmap(self._scale_pixmap())

    def sizeHint(self):
        """Provide size hint based on aspect ratio"""
        if hasattr(self, '_pixmap') and self._pixmap is not None:
            return self._pixmap.size()
        return QSize(256, 240)  # Default NES resolution

    def minimumSizeHint(self):
        """Provide minimum size hint"""
        return QSize(256, 240)

from videogames_utils.replay import replay_bk2
from stable_retro.enums import State
import stable_retro as retro

from .utils import (detect_game_from_filename, find_rom_integration_path, load_variables_json,
                     is_first_replay_in_run, find_annotated_events_for_replay)


class VideoPlayer(QWidget):
    """Widget for playing back .bk2 replay files"""

    frame_changed = pyqtSignal(int)  # Emits current frame index
    playback_finished = pyqtSignal()
    button_list_changed = pyqtSignal(list)  # Emits list of button names
    button_states_changed = pyqtSignal(dict)  # Emits dict of button states

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.current_frame_idx = 0
        self.is_playing = False
        self.fps = 60  # Default NES/Genesis FPS
        self.replay_info = None
        self.variables_data = {}  # Game variables including button states

        self.init_ui()

        # Playback timer - use precise timer for accurate 60Hz playback
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance_frame)
        
        # Elapsed timer for frame rate compensation
        self.elapsed_timer = QElapsedTimer()
        self.last_frame_time = 0
        self.frame_accumulator = 0.0  # Accumulate fractional frames

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Video display
        video_group = QGroupBox("Replay Video")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(2, 2, 2, 2)  # Minimal padding

        self.video_label = AspectRatioLabel()
        self.video_label.setMinimumSize(256, 240)  # Minimum NES resolution
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("QLabel { background-color: black; }")
        self.video_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        video_layout.addWidget(self.video_label)

        video_group.setLayout(video_layout)
        video_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        video_group.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(video_group)

        # Controls (under video only)
        controls_container = QWidget()
        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_container.setLayout(controls_layout)

        # Buttons row
        buttons_layout = QHBoxLayout()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.play_button.setEnabled(False)
        buttons_layout.addWidget(self.play_button)

        self.backward_button = QPushButton("<<")
        self.backward_button.clicked.connect(self.step_backward)
        self.backward_button.setEnabled(False)
        buttons_layout.addWidget(self.backward_button)

        self.forward_button = QPushButton(">>")
        self.forward_button.clicked.connect(self.step_forward)
        self.forward_button.setEnabled(False)
        buttons_layout.addWidget(self.forward_button)

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_playback)
        self.reset_button.setEnabled(False)
        buttons_layout.addWidget(self.reset_button)

        controls_layout.addLayout(buttons_layout)

        # Frame slider (under buttons)
        slider_layout = QHBoxLayout()

        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)
        self.frame_slider.setEnabled(False)
        slider_layout.addWidget(self.frame_slider)

        self.frame_label = QLabel("Frame: 0 / 0")
        slider_layout.addWidget(self.frame_label)

        controls_layout.addLayout(slider_layout)

        # Status label
        self.status_label = QLabel("No replay loaded")
        controls_layout.addWidget(self.status_label)

        layout.addWidget(controls_container)

        self.setLayout(layout)

    def load_replay(self, replay_info: Dict, dataset_path: Path):
        """
        Load a .bk2 replay file

        Args:
            replay_info: Dictionary with replay information (from get_replay_info)
            dataset_path: Path to the dataset root
        """
        self.status_label.setText("Loading replay...")
        self.frames = []
        self.current_frame_idx = 0
        self.replay_info = replay_info

        bk2_path = replay_info['path']
        game_type = detect_game_from_filename(bk2_path.name)

        # Find the ROM integration directory
        rom_integration_path = find_rom_integration_path(dataset_path, game_type)

        if not rom_integration_path:
            self.status_label.setText(f"Error: ROM not found for {game_type} in stimuli/")
            raise FileNotFoundError(
                f"ROM integration directory not found for {game_type}.\n"
                f"Expected in: {dataset_path / 'stimuli'}\n"
                f"Please ensure the ROM files are present in the dataset's stimuli/ folder."
            )

        try:
            # Add ROM integration path to stable_retro's search paths
            self.status_label.setText(f"Setting up ROM from {rom_integration_path.name}...")

            # Add the parent directory (stimuli/) to retro's integration paths
            retro.data.Integrations.add_custom_path(str(rom_integration_path.parent))

            # Determine if we need to skip the first step
            # First replay of each run needs skip_first_step=True
            skip_first = replay_info.get('skip_first_step', False)

            # Load frames from .bk2 replay
            self.status_label.setText(f"Replaying {bk2_path.name}...")

            replay_gen = replay_bk2(
                str(bk2_path),
                skip_first_step=skip_first,
                state=State.NONE,
                game=None,  # Auto-detect from .bk2
                scenario=None,
                inttype=retro.data.Integrations.CUSTOM_ONLY
            )

            frame_count = 0
            for frame, keys, annotations, audio_chunk, audio_rate, truncate, actions, state in replay_gen:
                self.frames.append(frame)
                frame_count += 1

                # Update status every 100 frames
                if frame_count % 100 == 0:
                    self.status_label.setText(f"Loading... {frame_count} frames")

            self.status_label.setText(f"Loaded {len(self.frames)} frames")

            # Load variables for button states
            variables_path = bk2_path.parent / (bk2_path.stem + '_variables.json')
            if variables_path.exists():
                self.variables_data = load_variables_json(variables_path)
                # Emit button list for external controller widget
                button_list = self.variables_data.get('actions', [])
                self.button_list_changed.emit(button_list)
            else:
                self.variables_data = {}

            # Setup controls
            self.frame_slider.setMaximum(len(self.frames) - 1)
            self.frame_slider.setValue(0)
            self.frame_slider.setEnabled(True)

            self.play_button.setEnabled(True)
            self.forward_button.setEnabled(True)
            self.backward_button.setEnabled(True)
            self.reset_button.setEnabled(True)

            # Display first frame
            self.display_frame(0)

        except Exception as e:
            self.status_label.setText(f"Error loading replay: {e}")
            print(f"Error loading replay: {e}")
            import traceback
            traceback.print_exc()

    def display_frame(self, frame_idx: int):
        """Display a specific frame"""
        if not self.frames or frame_idx < 0 or frame_idx >= len(self.frames):
            return

        self.current_frame_idx = frame_idx

        # Get frame (numpy array in RGB or BGR format)
        frame = self.frames[frame_idx]

        # Convert to QImage
        # stable_retro returns RGB, shape (H, W, 3)
        height, width, channels = frame.shape
        bytes_per_line = channels * width

        q_image = QImage(
            frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888
        )

        # Create pixmap and let AspectRatioLabel handle scaling
        pixmap = QPixmap.fromImage(q_image)
        self.video_label.setPixmap(pixmap)

        # Update UI
        self.frame_label.setText(f"Frame: {frame_idx} / {len(self.frames) - 1}")
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(frame_idx)
        self.frame_slider.blockSignals(False)

        # Update controller button states
        if self.variables_data:
            button_states = {}
            for button in self.variables_data.get('actions', []):
                if button in self.variables_data:
                    button_data = self.variables_data[button]
                    if isinstance(button_data, list) and frame_idx < len(button_data):
                        button_states[button] = bool(button_data[frame_idx])
            self.button_states_changed.emit(button_states)

        # Emit signal
        self.frame_changed.emit(frame_idx)

    def toggle_playback(self):
        """Toggle play/pause"""
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        """Start playback"""
        if not self.frames:
            return

        self.is_playing = True
        self.play_button.setText("Pause")

        # Reset timing - record where we started from for time-based advancement
        self._playback_start_frame = self.current_frame_idx
        self.elapsed_timer.start()
        self.last_frame_time = 0
        self.frame_accumulator = 0.0
        
        # Use a fast timer (every 8ms ~= 125Hz) for smooth catchup
        # The advance_frame method will handle actual frame timing
        self.timer.start(8)

    def pause(self):
        """Pause playback"""
        self.is_playing = False
        self.play_button.setText("Play")
        self.timer.stop()

    def advance_frame(self):
        """Advance to next frame (called by timer)
        
        Uses elapsed time to determine how many frames to advance,
        ensuring accurate 60Hz playback even if individual frames
        take longer to process.
        """
        if not self.elapsed_timer.isValid():
            return
            
        # Calculate elapsed time since playback started
        elapsed_ms = self.elapsed_timer.elapsed()
        
        # Calculate which frame we should be on based on elapsed time
        target_frame_float = (elapsed_ms / 1000.0) * self.fps
        target_frame = int(target_frame_float) + self._playback_start_frame
        
        # Clamp to valid range
        target_frame = min(target_frame, len(self.frames) - 1)
        
        # Only update if we need to advance
        if target_frame > self.current_frame_idx:
            self.display_frame(target_frame)
        
        # Check if we've reached the end
        if self.current_frame_idx >= len(self.frames) - 1:
            self.pause()
            self.playback_finished.emit()

    def step_forward(self):
        """Step forward one frame"""
        was_playing = self.is_playing
        self.pause()

        if self.current_frame_idx < len(self.frames) - 1:
            self.display_frame(self.current_frame_idx + 1)

        if was_playing:
            self.play()

    def step_backward(self):
        """Step backward one frame"""
        was_playing = self.is_playing
        self.pause()

        if self.current_frame_idx > 0:
            self.display_frame(self.current_frame_idx - 1)

        if was_playing:
            self.play()

    def reset_playback(self):
        """Reset to the first frame"""
        was_playing = self.is_playing
        self.pause()
        self.display_frame(0)

    def on_slider_changed(self, value: int):
        """Handle slider value change"""
        if value != self.current_frame_idx:
            self.display_frame(value)

    def get_current_time(self) -> float:
        """Get current playback time in seconds"""
        if not self.frames:
            return 0.0
        return self.current_frame_idx / self.fps

    def seek_to_time(self, time_seconds: float):
        """Seek to a specific time in seconds"""
        if not self.frames:
            return

        frame_idx = int(time_seconds * self.fps)
        frame_idx = max(0, min(frame_idx, len(self.frames) - 1))
        self.display_frame(frame_idx)

