"""Entry-point mode selection without running the expensive RNA pipeline."""

import sys
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "Orthogonal_sequence_selection"
sys.path.insert(0, str(SCRIPT_DIR))
import run_orthogonal_selection as runner  # noqa: E402


class EntryModeTests(unittest.TestCase):
    def test_no_arguments_open_gui(self) -> None:
        with patch.object(runner, "_run_gui", return_value=0) as gui:
            self.assertEqual(runner.main([]), 0)
        gui.assert_called_once()

    def test_gui_options_prefill_fields(self) -> None:
        with patch.object(runner, "_run_gui", return_value=0) as gui:
            self.assertEqual(
                runner.main(["--gui", "-N", "10", "-C", "5", "-R", "2000", "-G", "acgu", "-O", "pool.txt"]),
                0,
            )
        args, guides = gui.call_args.args
        self.assertEqual((args.num_nt, args.gc_count, args.rounds, args.output), (10, 5, 2000, "pool.txt"))
        self.assertEqual(guides, ["ACGU"])

    def test_pipeline_options_stay_noninteractive(self) -> None:
        with patch.object(runner, "_run_pipeline") as pipeline:
            self.assertEqual(runner.main(["-N", "9"]), 0)
            self.assertEqual(runner.main(["--cli"]), 0)
        self.assertEqual(pipeline.call_count, 2)

    def test_help_exits_before_gui(self) -> None:
        with patch.object(runner, "_run_gui") as gui:
            with redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as result:
                    runner.main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("--gui", output.getvalue())
        gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
