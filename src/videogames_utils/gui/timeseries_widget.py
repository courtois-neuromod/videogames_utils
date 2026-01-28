"""
Timeseries plotting widget for game variables
"""

from pathlib import Path
from typing import Dict, List, Optional
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QGroupBox, QRadioButton, QButtonGroup, QCheckBox, QScrollArea,
    QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
import pyqtgraph as pg

from .utils import load_variables_json, compute_zscore, GAME_CONFIGS


class TimeseriesWidget(QWidget):
    """Widget for displaying game variables as timeseries"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.variables_data = {}
        self.selected_variables = []
        self.use_zscore = False
        self.use_overlay = True  # Overlay all on same plot vs stacked (default: overlay)
        self.current_frame = 0
        self.fps = 60
        self.plots = {}
        self.position_lines = {}
        self.legend = None

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()

        # Top row: Display mode and Plot mode options (horizontal)
        options_layout = QHBoxLayout()

        # Normalization options
        norm_group = QGroupBox("Display Mode")
        norm_layout = QHBoxLayout()

        self.raw_radio = QRadioButton("Raw Values")
        self.raw_radio.setChecked(True)
        self.raw_radio.toggled.connect(self.on_normalization_changed)

        self.zscore_radio = QRadioButton("Z-Scored")
        self.zscore_radio.toggled.connect(self.on_normalization_changed)

        norm_layout.addWidget(self.raw_radio)
        norm_layout.addWidget(self.zscore_radio)
        norm_group.setLayout(norm_layout)
        options_layout.addWidget(norm_group)

        # Plot mode options
        plot_mode_group = QGroupBox("Plot Mode")
        plot_mode_layout = QHBoxLayout()

        self.stacked_radio = QRadioButton("Stacked")
        self.stacked_radio.toggled.connect(self.on_plot_mode_changed)

        self.overlay_radio = QRadioButton("Overlay")
        self.overlay_radio.setChecked(True)
        self.overlay_radio.toggled.connect(self.on_plot_mode_changed)

        plot_mode_layout.addWidget(self.stacked_radio)
        plot_mode_layout.addWidget(self.overlay_radio)
        plot_mode_group.setLayout(plot_mode_layout)
        options_layout.addWidget(plot_mode_group)

        options_layout.addStretch()  # Push options to the left
        layout.addLayout(options_layout)

        # Bottom row: Variables list (left) and plots (right)
        content_layout = QHBoxLayout()

        # Variable selection (left)
        var_group = QGroupBox("Variables")
        var_layout = QVBoxLayout()

        # Deselect all button (removed Select All)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.deselect_all_variables)
        var_layout.addWidget(self.deselect_all_btn)

        # Variable list with checkboxes
        self.var_list_widget = QListWidget()
        self.var_list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        var_layout.addWidget(self.var_list_widget)

        var_group.setLayout(var_layout)
        var_group.setMaximumWidth(250)
        content_layout.addWidget(var_group)

        # Plot area with scroll (right)
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_scroll.setMinimumWidth(300)

        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_scroll.setWidget(self.plot_widget)

        content_layout.addWidget(self.plot_scroll)

        layout.addLayout(content_layout)

        self.setLayout(layout)

    def load_variables(self, json_path: Path, fps: int = 60):
        """Load variables from JSON file"""
        self.variables_data = load_variables_json(json_path)
        self.fps = fps

        # Populate variable list
        self.var_list_widget.clear()
        self.var_checkboxes = {}

        # Filter to only include numeric list variables
        for var_name, var_data in sorted(self.variables_data.items()):
            if isinstance(var_data, list) and len(var_data) > 0:
                # Check if it's numeric
                try:
                    first_val = var_data[0]
                    if isinstance(first_val, (int, float, np.number)):
                        item = QCheckBox(var_name)
                        item.stateChanged.connect(self.on_variable_selection_changed)
                        self.var_list_widget.addItem("")
                        self.var_list_widget.setItemWidget(
                            self.var_list_widget.item(self.var_list_widget.count() - 1),
                            item
                        )
                        self.var_checkboxes[var_name] = item
                except (TypeError, IndexError):
                    pass

    def select_all_variables(self):
        """Select all variables"""
        for checkbox in self.var_checkboxes.values():
            checkbox.setChecked(True)

    def deselect_all_variables(self):
        """Deselect all variables"""
        for checkbox in self.var_checkboxes.values():
            checkbox.setChecked(False)

    def on_variable_selection_changed(self):
        """Handle variable selection change"""
        self.selected_variables = [
            var_name for var_name, checkbox in self.var_checkboxes.items()
            if checkbox.isChecked()
        ]
        self.update_plots()

    def on_normalization_changed(self):
        """Handle normalization mode change"""
        self.use_zscore = self.zscore_radio.isChecked()
        self.update_plots()

    def on_plot_mode_changed(self):
        """Handle plot mode change"""
        self.use_overlay = self.overlay_radio.isChecked()
        self.update_plots()

    def update_plots(self):
        """Update the plots based on selected variables"""
        # Clear existing plots
        self.plot_widget.clear()
        self.plots = {}
        self.position_lines = {}
        self.legend = None

        if not self.selected_variables:
            return

        if self.use_overlay:
            # Overlay mode: all variables on same plot with different colors
            self._create_overlay_plot()
        else:
            # Stacked mode: separate plot for each variable
            self._create_stacked_plots()

    def _create_stacked_plots(self):
        """Create separate plots for each variable"""
        for idx, var_name in enumerate(self.selected_variables):
            var_data = self.variables_data.get(var_name, [])
            if not var_data:
                continue

            # Convert to numpy array
            data = np.array(var_data, dtype=float)

            # Apply normalization
            if self.use_zscore:
                data = compute_zscore(data)

            # Create plot
            plot = self.plot_widget.addPlot(row=idx, col=0)
            plot.setLabel('left', var_name)
            plot.setLabel('bottom', 'Frame')
            plot.showGrid(x=True, y=True, alpha=0.3)

            # Plot data
            time_axis = np.arange(len(data))
            curve = plot.plot(time_axis, data, pen='y')

            # Add vertical line for current position
            position_line = pg.InfiniteLine(
                pos=self.current_frame,
                angle=90,
                pen=pg.mkPen('r', width=2),
                movable=False
            )
            plot.addItem(position_line)

            self.plots[var_name] = plot
            self.position_lines[var_name] = position_line

        # Link x-axes for synchronized zooming/panning
        if len(self.plots) > 1:
            first_plot = list(self.plots.values())[0]
            for plot in list(self.plots.values())[1:]:
                plot.setXLink(first_plot)

    def _create_overlay_plot(self):
        """Create a single plot with all variables overlaid"""
        # Color palette for different variables
        colors = [
            (255, 0, 0),      # Red
            (0, 255, 0),      # Green
            (0, 0, 255),      # Blue
            (255, 255, 0),    # Yellow
            (255, 0, 255),    # Magenta
            (0, 255, 255),    # Cyan
            (255, 128, 0),    # Orange
            (128, 0, 255),    # Purple
            (0, 255, 128),    # Spring green
            (255, 0, 128),    # Pink
        ]

        # Create single plot
        plot = self.plot_widget.addPlot(row=0, col=0)
        plot.setLabel('bottom', 'Frame')

        if self.use_zscore:
            plot.setLabel('left', 'Z-Score')
        else:
            plot.setLabel('left', 'Value')

        plot.showGrid(x=True, y=True, alpha=0.3)

        # Plot each variable with different color
        plot_items = []
        for idx, var_name in enumerate(self.selected_variables):
            var_data = self.variables_data.get(var_name, [])
            if not var_data:
                continue

            # Convert to numpy array
            data = np.array(var_data, dtype=float)

            # Apply normalization
            if self.use_zscore:
                data = compute_zscore(data)

            # Get color (cycle through if more than palette size)
            color = colors[idx % len(colors)]
            pen = pg.mkPen(color=color, width=2)

            # Plot data
            time_axis = np.arange(len(data))
            curve = plot.plot(time_axis, data, pen=pen, name=var_name)
            plot_items.append((var_name, curve))

        # Add legend outside on the left
        legend = pg.LegendItem(offset=(5, 5))
        legend.setParentItem(plot.getViewBox())
        legend.anchor((0, 0), (0, 0))  # Anchor to top-left
        for name, item in plot_items:
            legend.addItem(item, name)

        # Add single vertical line for current position
        position_line = pg.InfiniteLine(
            pos=self.current_frame,
            angle=90,
            pen=pg.mkPen('w', width=2, style=Qt.PenStyle.DashLine),
            movable=False
        )
        plot.addItem(position_line)

        # Store for updates
        self.plots['overlay'] = plot
        self.position_lines['overlay'] = position_line

    def update_position(self, frame_idx: int):
        """Update the position indicator on all plots"""
        self.current_frame = frame_idx

        # Update position lines
        for line in self.position_lines.values():
            line.setPos(frame_idx)

    def get_time_axis(self, n_frames: int) -> np.ndarray:
        """Get time axis in seconds"""
        return np.arange(n_frames) / self.fps
