"""Regression checks for configurable G/C positions in candidate generation."""

import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Orthogonal_sequence_selection" / "functions"))
import generate_pool_nnt as generator  # noqa: E402
sys.path.insert(0, str(ROOT / "Orthogonal_sequence_selection"))
import run_orthogonal_selection as runner  # noqa: E402


class GcCountTests(unittest.TestCase):
    def test_default_9nt_output_matches_legacy(self) -> None:
        patterns = generator.gen_pattern_sw(9)
        sequences = generator.generate_sequences(9)
        digest = lambda rows: hashlib.sha256("\n".join(rows).encode()).hexdigest()
        self.assertEqual(len(patterns), 99)
        self.assertEqual(digest(patterns), "6938ee3fe8fa61794c83caed3f2b3d56a9b4cd161a8e4f45e7f597bbade60265")
        self.assertEqual(len(sequences), 8918)
        self.assertEqual(digest(sequences), "cff7f87538f75004841bee6de51d4b5a1bec476d1ef5d007939c3422f340a09f")

    def test_custom_counts_are_exact(self) -> None:
        for gc_count in (3, 5):
            with self.subTest(gc_count=gc_count):
                patterns = generator.gen_pattern_sw(9, gc_count)
                self.assertTrue(patterns)
                self.assertTrue(all(p.count("s") == gc_count for p in patterns))
                self.assertTrue(all("ssss" not in p and "wwww" not in p for p in patterns))
                sequences = generator.generate_sequences(9, gc_count)
                self.assertTrue(sequences)
                self.assertTrue(
                    all(sum(base in "GC" for base in seq) == gc_count for seq in sequences)
                )

    def test_invalid_counts_are_rejected(self) -> None:
        for gc_count in (1, 8):
            with self.subTest(gc_count=gc_count):
                with self.assertRaisesRegex(ValueError, "GC count"):
                    generator.generate_sequences(9, gc_count)

    def test_standalone_cli_writes_custom_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "pool.txt"
            with redirect_stdout(io.StringIO()):
                generator.main(["8", "-C", "3", "--output", str(output_file)])
            sequences = output_file.read_text().splitlines()
            self.assertTrue(sequences)
            self.assertTrue(all(sum(base in "GC" for base in seq) == 3 for seq in sequences))

    def test_runner_passes_count_to_generator(self) -> None:
        class StopAfterFirstStep(Exception):
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            args = runner.parse_args(["--cli", "-N", "9", "-C", "5"])
            with patch.object(runner.Path, "cwd", return_value=Path(temp_dir)):
                with patch.object(runner, "_run", side_effect=StopAfterFirstStep) as run:
                    with redirect_stdout(io.StringIO()):
                        with self.assertRaises(StopAfterFirstStep):
                            runner._run_pipeline(args)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--gc-count") + 1], "5")


if __name__ == "__main__":
    unittest.main()
