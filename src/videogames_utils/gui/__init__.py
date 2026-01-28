"""
Video Game Replay Visualizer GUI
Interactive tool for exploring CNeuroMod videogame datasets
"""

import argparse
import os
from pathlib import Path
from .main_window import ReplayVisualizerApp


def main():
    """Entry point for the GUI application"""
    import sys
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Video Game Replay Visualizer - Interactive tool for exploring CNeuroMod videogame datasets'
    )
    parser.add_argument(
        '--n_jobs', '-j',
        type=int,
        default=1,
        help='Number of workers for brain plot precomputation. '
             'Default is 1 (minimal CPU impact). '
             'Use -1 for all available CPUs, or specify a number (e.g., 8).'
    )
    args = parser.parse_args()
    
    # Resolve n_jobs (-1 means all CPUs)
    n_jobs = args.n_jobs
    if n_jobs == -1:
        n_jobs = os.cpu_count() or 1
    elif n_jobs < 1:
        n_jobs = 1

    app = QApplication(sys.argv)
    app.setApplicationName("VG Replay Visualizer")
    
    # Set application icon
    icon_path = Path(__file__).parent / "resources" / "logo_neuromod_small.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = ReplayVisualizerApp(n_jobs=n_jobs)
    window.show()

    sys.exit(app.exec())


__all__ = ['main', 'ReplayVisualizerApp']
