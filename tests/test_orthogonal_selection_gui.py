"""Offscreen smoke test for GUI parameter help buttons."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    QtCore = None
    QtWidgets = None

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "Orthogonal_sequence_selection"
sys.path.insert(0, str(SCRIPT_DIR))


@unittest.skipUnless(QtWidgets is not None, "PySide6 is not installed")
class GuiHelpTests(unittest.TestCase):
    def test_five_parameter_help_buttons(self) -> None:
        import run_orthogonal_selection as runner

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        observed: dict[str, object] = {}

        def inspect_window() -> None:
            window = next(
                widget
                for widget in app.topLevelWidgets()
                if widget.windowTitle() == "Orthogonal RNA Sequence Selection"
            )
            buttons = window.findChildren(QtWidgets.QToolButton)
            observed["names"] = [button.accessibleName() for button in buttons]
            observed["styles"] = [button.styleSheet() for button in buttons]
            observed["gc_count"] = window.findChildren(QtWidgets.QSpinBox)[1].value()
            with patch.object(QtWidgets.QMessageBox, "information") as popup:
                for button in buttons:
                    button.click()
                observed["titles"] = [call.args[1] for call in popup.call_args_list]
                observed["explanations"] = [
                    call.args[2] for call in popup.call_args_list
                ]
            app.quit()

        QtCore.QTimer.singleShot(0, inspect_window)
        self.assertEqual(
            runner._run_gui(runner.parse_args([]), [runner.DEFAULT_GUIDE]),
            0,
        )
        self.assertEqual(
            observed["names"],
            [
                "Help for KL length (N):",
                "Help for GC count (C):",
                "Help for Selection rounds (R):",
                "Help for Guide RNA(s) (G):",
                "Help for Final filename (O):",
            ],
        )
        self.assertTrue(all("#DDF3FF" in style for style in observed["styles"]))
        self.assertEqual(observed["gc_count"], 4)
        self.assertEqual(
            observed["titles"],
            [
                "KL length (N)",
                "G/C base count (C)",
                "Selection rounds (R)",
                "Guide RNA sequences (G)",
                "Final output filename (O)",
            ],
        )
        self.assertTrue(
            all("Example" in explanation for explanation in observed["explanations"])
        )


if __name__ == "__main__":
    unittest.main()
