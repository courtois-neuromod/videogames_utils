"""
Physio visualization widget for displaying physiological data (PPG, ECG, RSP, EDA)
with scrolling timeseries and event markers.
"""

from pathlib import Path
from typing import Optional, Dict, List, Tuple
import gzip
import numpy as np
import pandas as pd

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QGroupBox, QScrollArea
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg


class PhysioWidget(QWidget):
    """Widget for displaying physiological timeseries with scrolling visualization"""

    # Physio channels and their display colors
    CHANNELS = {
        'PPG': '#ff6b6b',      # Red - photoplethysmography
        'ECG': '#4ecdc4',      # Teal - electrocardiogram
        'RSP': '#95e1d3',      # Light green - respiration
        'EDA': '#f9ca24',      # Yellow - electrodermal activity
        'EDATonic': '#f0932b', # Orange - tonic EDA component
        'EDAPhasic': '#eb4d4b' # Dark red - phasic EDA component
    }

    # Event types and their markers
    EVENT_TYPES = {
        'r_peak': {'color': '#ff0000', 'symbol': 'o', 'channel': 'ECG'},
        'r_peak_corrected': {'color': '#ff6666', 'symbol': 's', 'channel': 'ECG'},
        'systolic_peak': {'color': '#00ff00', 'symbol': 't', 'channel': 'PPG'},
        'systolic_peak_corrected': {'color': '#66ff66', 'symbol': 'd', 'channel': 'PPG'},
        'inspiration': {'color': '#00ffff', 'symbol': 't1', 'channel': 'RSP'},
        'expiration': {'color': '#0099ff', 'symbol': 't2', 'channel': 'RSP'},
        'scr_onset': {'color': '#ffff00', 'symbol': 'o', 'channel': 'EDA'},
        'scr_peak': {'color': '#ff9900', 'symbol': 's', 'channel': 'EDA'},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Data storage
        self.physio_data = None  # DataFrame with physio signals
        self.events_data = None  # DataFrame with physio events
        self.sampling_rate = 1000  # Hz (from preproc_physio.json)
        
        # Timing info
        self.onset_time = 0.0  # Onset time of replay in the run (seconds)
        self.replay_duration = None
        self.fps = 60
        self.current_frame = 0
        
        # Display settings
        self.window_duration = 5.0  # Visible window in seconds
        self.selected_channels = ['PPG', 'ECG', 'RSP', 'EDA']  # Default channels
        self.show_events = True
        
        # Plots
        self.plots = {}
        self.curves = {}
        self.event_scatter = {}
        self.position_lines = {}
        
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        # Top controls: Channel selection
        controls_layout = QHBoxLayout()
        
        # Channel checkboxes
        channel_group = QGroupBox("Channels")
        channel_layout = QHBoxLayout()
        channel_layout.setContentsMargins(5, 2, 5, 2)
        
        self.channel_checkboxes = {}
        for channel in ['PPG', 'ECG', 'RSP', 'EDA']:
            cb = QCheckBox(channel)
            cb.setChecked(channel in self.selected_channels)
            cb.stateChanged.connect(self.on_channel_selection_changed)
            cb.setStyleSheet(f"color: {self.CHANNELS[channel]};")
            channel_layout.addWidget(cb)
            self.channel_checkboxes[channel] = cb
        
        channel_group.setLayout(channel_layout)
        controls_layout.addWidget(channel_group)
        
        # Events checkbox
        self.events_checkbox = QCheckBox("Show Events")
        self.events_checkbox.setChecked(True)
        self.events_checkbox.stateChanged.connect(self.on_events_toggle)
        controls_layout.addWidget(self.events_checkbox)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Plot area
        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground('#1a1a1a')
        layout.addWidget(self.plot_widget)

        self.setLayout(layout)
        
        # Status label (shown when no data)
        self.status_label = QLabel("No physio data loaded")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888;")

    def load_physio(self, physio_path: Path, events_path: Optional[Path],
                    onset_time: float, fps: int = 60,
                    replay_duration: float = None, sampling_rate: int = 1000):
        """
        Load physiological data and events
        
        Args:
            physio_path: Path to physio TSV file (can be .tsv.gz)
            events_path: Path to physio events TSV file (optional)
            onset_time: Onset time of replay within the run (seconds)
            fps: Frames per second for the replay
            replay_duration: Duration of the replay in seconds
            sampling_rate: Sampling frequency of physio data (default 1000 Hz)
        """
        try:
            # Load physio timeseries
            if str(physio_path).endswith('.gz'):
                self.physio_data = pd.read_csv(physio_path, sep='\t', compression='gzip')
            else:
                self.physio_data = pd.read_csv(physio_path, sep='\t')
            
            # Load events if provided
            if events_path and events_path.exists():
                self.events_data = pd.read_csv(events_path, sep='\t')
            else:
                self.events_data = None
            
            # Store parameters
            self.onset_time = onset_time
            self.fps = fps
            self.replay_duration = replay_duration
            self.sampling_rate = sampling_rate
            
            # Update plots
            self._setup_plots()
            self.update_position(0)
            
        except Exception as e:
            print(f"Error loading physio data: {e}")
            import traceback
            traceback.print_exc()
            self.physio_data = None
            self.events_data = None

    def _setup_plots(self):
        """Set up the plot layout based on selected channels"""
        self.plot_widget.clear()
        self.plots = {}
        self.curves = {}
        self.event_scatter = {}
        self.position_lines = {}
        
        if self.physio_data is None:
            return
        
        # Get selected channels that exist in data
        channels_to_plot = [
            ch for ch in self.selected_channels 
            if ch in self.physio_data.columns
        ]
        
        if not channels_to_plot:
            return
        
        # Create stacked plots for each channel
        for idx, channel in enumerate(channels_to_plot):
            plot = self.plot_widget.addPlot(row=idx, col=0)
            plot.setLabel('left', channel)
            plot.setMouseEnabled(x=False, y=False)
            plot.hideAxis('bottom')
            plot.setXRange(0, self.window_duration, padding=0)
            
            # Style the plot
            plot.getAxis('left').setTextPen(self.CHANNELS[channel])
            plot.showGrid(x=False, y=True, alpha=0.3)
            
            # Create curve for the channel
            pen = pg.mkPen(color=self.CHANNELS[channel], width=1)
            curve = plot.plot([], [], pen=pen)
            self.curves[channel] = curve
            
            # Create scatter plot for events on this channel
            self.event_scatter[channel] = []
            
            # Create position line (current time indicator) - solid bright line on right edge
            pos_line = pg.InfiniteLine(
                pos=self.window_duration,  # Line on right side (current time t)
                angle=90,
                pen=pg.mkPen('#00ff00', width=3, style=Qt.PenStyle.SolidLine)
            )
            plot.addItem(pos_line)
            self.position_lines[channel] = pos_line
            
            self.plots[channel] = plot
        
        # Link X axes
        if len(channels_to_plot) > 1:
            first_plot = self.plots[channels_to_plot[0]]
            for channel in channels_to_plot[1:]:
                self.plots[channel].setXLink(first_plot)

    def update_position(self, frame_idx: int):
        """
        Update physio display based on current frame
        
        The display shows data "entering from the right and going to the left",
        like an ECG monitor. Current time is on the right edge.
        
        Args:
            frame_idx: Current frame index in the replay
        """
        if self.physio_data is None:
            return
        
        self.current_frame = frame_idx
        
        # Calculate time in replay (seconds)
        time_in_replay = frame_idx / self.fps
        
        # Calculate time in run
        time_in_run = time_in_replay + self.onset_time
        
        # Calculate sample range to display
        # Window shows [time_in_run - window_duration, time_in_run]
        end_sample = int(time_in_run * self.sampling_rate)
        start_sample = int((time_in_run - self.window_duration) * self.sampling_rate)
        
        # Clamp to valid range
        start_sample = max(0, start_sample)
        end_sample = min(len(self.physio_data), end_sample)
        
        if start_sample >= end_sample:
            return
        
        # Time axis for the window (0 = left edge = oldest, window_duration = right edge = current)
        num_samples = end_sample - start_sample
        time_axis = np.linspace(0, self.window_duration, num_samples)
        
        # Update each channel curve
        for channel, curve in self.curves.items():
            if channel in self.physio_data.columns:
                data = self.physio_data[channel].values[start_sample:end_sample]
                
                # Normalize for display (z-score within window)
                if len(data) > 0:
                    data_mean = np.nanmean(data)
                    data_std = np.nanstd(data)
                    if data_std > 0:
                        data_normalized = (data - data_mean) / data_std
                    else:
                        data_normalized = data - data_mean
                    
                    curve.setData(time_axis, data_normalized)
                    
                    # Auto-range Y axis
                    if channel in self.plots:
                        self.plots[channel].setYRange(
                            np.nanmin(data_normalized) - 0.5,
                            np.nanmax(data_normalized) + 0.5
                        )
        
        # Update event markers if enabled
        if self.show_events and self.events_data is not None:
            self._update_events(time_in_run)

    def _update_events(self, current_time: float):
        """Update event markers in the visible window"""
        # Clear existing event markers
        for channel, scatters in self.event_scatter.items():
            for scatter in scatters:
                if channel in self.plots:
                    self.plots[channel].removeItem(scatter)
            self.event_scatter[channel] = []
        
        if self.events_data is None:
            return
        
        # Get events in visible window
        window_start = current_time - self.window_duration
        window_end = current_time
        
        visible_events = self.events_data[
            (self.events_data['onset'] >= window_start) &
            (self.events_data['onset'] <= window_end)
        ]
        
        # Group events by type and channel
        for event_type, event_props in self.EVENT_TYPES.items():
            type_events = visible_events[visible_events['trial_type'] == event_type]
            
            if len(type_events) == 0:
                continue
            
            channel = event_props['channel']
            if channel not in self.plots:
                continue
            
            # Convert onset times to window coordinates
            x_positions = type_events['onset'].values - window_start
            
            # Get y positions from the data at those times
            y_positions = []
            for onset in type_events['onset'].values:
                sample_idx = int(onset * self.sampling_rate)
                if 0 <= sample_idx < len(self.physio_data) and channel in self.physio_data.columns:
                    val = self.physio_data[channel].values[sample_idx]
                    # Normalize like the curve
                    window_start_sample = int((current_time - self.window_duration) * self.sampling_rate)
                    window_end_sample = int(current_time * self.sampling_rate)
                    window_start_sample = max(0, window_start_sample)
                    window_end_sample = min(len(self.physio_data), window_end_sample)
                    
                    if window_end_sample > window_start_sample:
                        window_data = self.physio_data[channel].values[window_start_sample:window_end_sample]
                        data_mean = np.nanmean(window_data)
                        data_std = np.nanstd(window_data)
                        if data_std > 0:
                            val = (val - data_mean) / data_std
                        else:
                            val = val - data_mean
                    y_positions.append(val)
                else:
                    y_positions.append(0)
            
            y_positions = np.array(y_positions)
            
            # Create scatter plot for these events
            scatter = pg.ScatterPlotItem(
                x=x_positions,
                y=y_positions,
                size=10,
                pen=pg.mkPen(event_props['color'], width=1),
                brush=pg.mkBrush(event_props['color']),
                symbol=event_props['symbol']
            )
            self.plots[channel].addItem(scatter)
            self.event_scatter[channel].append(scatter)

    def on_channel_selection_changed(self):
        """Handle channel selection change"""
        self.selected_channels = [
            ch for ch, cb in self.channel_checkboxes.items()
            if cb.isChecked()
        ]
        self._setup_plots()
        self.update_position(self.current_frame)

    def on_events_toggle(self):
        """Handle events visibility toggle"""
        self.show_events = self.events_checkbox.isChecked()
        self.update_position(self.current_frame)

    def clear(self):
        """Clear the widget"""
        self.physio_data = None
        self.events_data = None
        self.plot_widget.clear()
        self.plots = {}
        self.curves = {}
        self.event_scatter = {}
        self.position_lines = {}
