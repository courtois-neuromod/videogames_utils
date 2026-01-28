"""
Controller visualization widget showing button presses
"""

from typing import Dict, List
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QFont


class ControllerWidget(QWidget):
    """Widget for visualizing controller button presses"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.button_states = {}
        self.button_list = []
        self.setMinimumSize(300, 250)
        self.setMaximumWidth(400)

    def set_buttons(self, button_list: List[str]):
        """Set the list of buttons to display"""
        self.button_list = button_list
        self.button_states = {btn: False for btn in button_list}
        self.update()

    def update_button_states(self, button_states: Dict[str, bool]):
        """Update button states and trigger repaint"""
        self.button_states = button_states
        self.update()

    def paintEvent(self, event):
        """Draw the controller"""
        if not self.button_list:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Title
        painter.setPen(QColor(200, 200, 200))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(10, 20, "CONTROLLER")

        # D-Pad (left side)
        dpad_x = 50
        dpad_y = 60
        button_size = 35

        self._draw_dpad_button(painter, dpad_x + button_size, dpad_y, button_size, "UP", "↑")
        self._draw_dpad_button(painter, dpad_x, dpad_y + button_size, button_size, "LEFT", "←")
        self._draw_dpad_button(painter, dpad_x + button_size * 2, dpad_y + button_size, button_size, "RIGHT", "→")
        self._draw_dpad_button(painter, dpad_x + button_size, dpad_y + button_size * 2, button_size, "DOWN", "↓")

        # Action buttons (right side)
        action_x = 200
        action_y = 80
        radius = 20

        # Check which buttons are available
        has_xy = 'X' in self.button_list or 'Y' in self.button_list
        has_lr = 'L' in self.button_list or 'R' in self.button_list

        if has_xy:
            # SNES-style layout (X, Y, A, B)
            self._draw_round_button(painter, action_x, action_y - 35, radius, "X")
            self._draw_round_button(painter, action_x - 35, action_y, radius, "Y")
            self._draw_round_button(painter, action_x + 35, action_y, radius, "A")
            self._draw_round_button(painter, action_x, action_y + 35, radius, "B")
        else:
            # NES/Genesis-style layout (just A, B)
            self._draw_round_button(painter, action_x, action_y, radius, "B")
            self._draw_round_button(painter, action_x + 45, action_y, radius, "A")

            # Add C button for Genesis
            if 'C' in self.button_list:
                self._draw_round_button(painter, action_x + 90, action_y, radius, "C")

        # Shoulder buttons
        if has_lr:
            shoulder_y = 40
            if 'L' in self.button_list:
                self._draw_shoulder_button(painter, 30, shoulder_y, "L")
            if 'R' in self.button_list:
                self._draw_shoulder_button(painter, 230, shoulder_y, "R")

        # Start/Select
        start_y = 180
        if 'SELECT' in self.button_list:
            self._draw_small_button(painter, 80, start_y, "SELECT")
        if 'START' in self.button_list:
            self._draw_small_button(painter, 180, start_y, "START")
        if 'MODE' in self.button_list:
            self._draw_small_button(painter, 130, start_y, "MODE")

    def _draw_dpad_button(self, painter: QPainter, x: int, y: int, size: int, name: str, symbol: str):
        """Draw a D-pad button"""
        is_active = self.button_states.get(name, False)

        # Fill color
        if is_active:
            painter.setBrush(QColor(100, 255, 100))
        else:
            painter.setBrush(QColor(50, 50, 50))

        # Border
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawRect(x, y, size, size)

        # Symbol
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(x, y, size, size), Qt.AlignmentFlag.AlignCenter, symbol)

    def _draw_round_button(self, painter: QPainter, x: int, y: int, radius: int, name: str):
        """Draw a round action button"""
        is_active = self.button_states.get(name, False)

        # Fill color
        if is_active:
            painter.setBrush(QColor(100, 255, 100))
        else:
            painter.setBrush(QColor(50, 50, 50))

        # Border
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)

        # Label
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2),
                        Qt.AlignmentFlag.AlignCenter, name)

    def _draw_shoulder_button(self, painter: QPainter, x: int, y: int, name: str):
        """Draw a shoulder button"""
        is_active = self.button_states.get(name, False)

        width, height = 50, 25

        # Fill color
        if is_active:
            painter.setBrush(QColor(100, 255, 100))
        else:
            painter.setBrush(QColor(50, 50, 50))

        # Border
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.drawRoundedRect(x, y, width, height, 5, 5)

        # Label
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(x, y, width, height), Qt.AlignmentFlag.AlignCenter, name)

    def _draw_small_button(self, painter: QPainter, x: int, y: int, name: str):
        """Draw a small button (START/SELECT/MODE)"""
        is_active = self.button_states.get(name, False)

        width, height = 60, 20

        # Fill color
        if is_active:
            painter.setBrush(QColor(100, 255, 100))
        else:
            painter.setBrush(QColor(50, 50, 50))

        # Border
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawRoundedRect(x - width // 2, y, width, height, 3, 3)

        # Label
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(QRect(x - width // 2, y, width, height),
                        Qt.AlignmentFlag.AlignCenter, name)
