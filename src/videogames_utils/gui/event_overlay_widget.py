"""
Event overlay widget for displaying events as they occur
"""

from typing import List, Dict
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
import time


class EventOverlayWidget(QWidget):
    """Widget for displaying events as overlay notifications"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_events = []  # List of {text, start_time, duration, color}
        self.fps = 60
        self.setMinimumHeight(80)
        self.setMaximumHeight(100)

        # Timer to update fading
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start(16)  # ~60 FPS update

    def add_event(self, event_text: str, duration: float = 0.5, color: QColor = None):
        """
        Add an event to display

        Args:
            event_text: Event description
            duration: How long to display (seconds)
            color: Color for the event text
        """
        if color is None:
            color = QColor(100, 255, 100)  # Default green

        self.active_events.append({
            'text': event_text,
            'start_time': time.time(),
            'duration': duration,
            'color': color
        })

    def update_events(self, current_events: List[Dict], frame_time: float):
        """
        Update events based on current frame time

        Args:
            current_events: List of event dicts with 'type' and 'time_in_event'
            frame_time: Current time in seconds
        """
        # Add new events that just started (time_in_event < 1 frame)
        frame_duration = 1.0 / self.fps

        for event in current_events:
            time_in_event = event.get('time_in_event', 0)

            # If event just started (within one frame)
            if time_in_event < frame_duration:
                event_type = event['type']

                # Color based on event type
                if 'JUMP' in event_type.upper():
                    color = QColor(100, 200, 255)  # Blue for jumps
                elif 'RIGHT' in event_type or 'LEFT' in event_type:
                    color = QColor(255, 200, 100)  # Orange for movement
                elif 'HIT' in event_type.upper() or 'FALL' in event_type.upper():
                    color = QColor(255, 100, 100)  # Red for damage
                elif 'COIN' in event_type.upper():
                    color = QColor(255, 255, 100)  # Yellow for coins
                elif 'POWERUP' in event_type.upper():
                    color = QColor(255, 100, 255)  # Magenta for powerups
                elif 'ENEMY' in event_type.upper() or 'KILL' in event_type.upper():
                    color = QColor(255, 150, 0)  # Orange-red for kills
                else:
                    color = QColor(150, 255, 150)  # Light green default

                self.add_event(event_type, duration=0.5, color=color)

    def paintEvent(self, event):
        """Draw the active events"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        current_time = time.time()

        # Remove expired events and draw active ones
        self.active_events = [e for e in self.active_events
                             if current_time - e['start_time'] < e['duration']]

        if not self.active_events:
            return

        # Draw events stacked vertically
        y_offset = 10
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)

        for event_data in self.active_events:
            elapsed = current_time - event_data['start_time']
            progress = elapsed / event_data['duration']

            # Calculate fade (fade out in last 50% of duration)
            if progress > 0.5:
                alpha = int(255 * (1 - (progress - 0.5) * 2))
            else:
                alpha = 255

            color = QColor(event_data['color'])
            color.setAlpha(alpha)

            painter.setPen(color)

            # Draw text with shadow for visibility
            shadow_color = QColor(0, 0, 0, alpha // 2)
            painter.setPen(shadow_color)
            painter.drawText(11, y_offset + 1, event_data['text'])

            painter.setPen(color)
            painter.drawText(10, y_offset, event_data['text'])

            y_offset += 20

    def clear_events(self):
        """Clear all active events"""
        self.active_events = []
        self.update()
