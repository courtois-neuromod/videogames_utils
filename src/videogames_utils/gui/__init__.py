"""
Video Game Replay Visualizer GUI
Interactive tool for exploring CNeuroMod videogame datasets
"""

from .main_window import ReplayVisualizerApp


def main():
    """Entry point for the GUI application"""
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("VG Replay Visualizer")

    window = ReplayVisualizerApp()
    window.show()

    sys.exit(app.exec())


__all__ = ['main', 'ReplayVisualizerApp']
