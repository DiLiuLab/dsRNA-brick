#!/usr/bin/env python3
"""
Run the full orthogonal KL selection pipeline with one command.

Pipeline:
1) generate_pool_nnt.py
2) build_rna_conflict_graphV2.py
3) select_from_conflict_graph.py
4) pool_rna_complement.py (complement file + orthogonality figure)

All outputs are written into a new folder:
  Orthogonal_RNA_Pool_<N>nt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_GUIDE = "CACGAAGUCAAUAC"
DEFAULT_GC_COUNT = 4


def _add_suffix_to_path(path: str, suffix: str) -> str:
    p = Path(path)
    if p.suffix:
        return str(p.with_name(f"{p.stem}{suffix}{p.suffix}"))
    return f"{path}{suffix}"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"\n[RUN] {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _normalize_guides(raw_guides: list[str] | None) -> list[str]:
    if not raw_guides:
        return [DEFAULT_GUIDE]
    guides: list[str] = []
    for g in raw_guides:
        for part in g.replace(",", " ").split():
            if part.strip():
                guides.append(part.strip().upper())
    return guides or [DEFAULT_GUIDE]


def _print_user_instructions() -> None:
    print(
        """
Usage:
  python run_orthogonal_selection.py           # GUI
  python run_orthogonal_selection.py --gui     # GUI
  python run_orthogonal_selection.py -N 9      # command line

Options:
  -N, --num-nt   KL length N (default: 9)
  -C, --gc-count Exact number of G/C bases per KL (default: 4)
  -R, --rounds   Number of randomized attempts in step 3 (default: 1000)
  -G, --guide    Guide sequence. Can be used multiple times.
                 Default guide: CACGAAGUCAAUAC
  -O, --output   Final output filename for step 4.
                 Default: Orthogonal_RNA_Pool_<N>nt.txt
  --gui          Open the GUI (other options prefill its fields).
  --cli          Run the pipeline with defaults without opening the GUI.
  -h, --help     Show the standard argument list.
  -U, --User     Show this instruction text.

Examples:
  python run_orthogonal_selection.py --gui
  python run_orthogonal_selection.py --gui -N 9 -R 2000
  python run_orthogonal_selection.py -N 9 -C 5
  python run_orthogonal_selection.py --cli
  python run_orthogonal_selection.py -N 9 -R 2000
  python run_orthogonal_selection.py -G CACGAAGUCAAUAC -G GGGAAAUUU
  python run_orthogonal_selection.py -O MyFinalPool.txt

Output folder (auto-created):
  Orthogonal_RNA_Pool_<N>nt

Output files inside that folder:
  RNA_Pool_<N>nt.txt
  FilteredPool_<N>nt.txt
  ConflictGraph_<N>nt.txt
  SelectedPool_from_graph.txt
  Orthogonal_RNA_Pool_<N>nt.txt      (or filename from -O)
  orthogonality_<N>nt_RNA_Pool.png
""".strip()
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run orthogonal KL selection end-to-end.",
    )
    parser.add_argument("-N", "--num-nt", type=int, default=9, help="KL length N (default: 9).")
    parser.add_argument(
        "-C", "--gc-count", type=int, default=DEFAULT_GC_COUNT,
        help="Exact number of G/C bases per KL (default: 4; range: 2 to N-2).",
    )
    parser.add_argument(
        "-R",
        "--rounds",
        type=int,
        default=1000,
        help="Number of randomized attempts in step 3 (default: 1000).",
    )
    parser.add_argument(
        "-G",
        "--guide",
        action="append",
        default=None,
        help=(
            "Guide sequence. Can be provided multiple times. "
            f"Default: {DEFAULT_GUIDE}"
        ),
    )
    parser.add_argument(
        "-O",
        "--output",
        type=str,
        default=None,
        help="Final output text filename for step 4.",
    )
    parser.add_argument(
        "-U",
        "--User",
        action="store_true",
        help="Show instruction of how to use this python file.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gui", action="store_true", help="Open the parameter-entry GUI.")
    mode.add_argument("--cli", action="store_true", help="Run the CLI pipeline with defaults.")
    return parser.parse_args(argv)


def _replace_file(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Expected file not found: {src}")
    if dst.exists():
        dst.unlink()
    src.replace(dst)


def _run_pipeline(args: argparse.Namespace) -> None:
    if args.num_nt <= 0:
        raise ValueError("--num-nt must be positive.")
    if not 2 <= args.gc_count <= args.num_nt - 2:
        raise ValueError("--gc-count must be between 2 and N-2 so all four bases can appear.")
    if args.rounds <= 0:
        raise ValueError("--rounds must be positive.")

    guides = _normalize_guides(args.guide)

    script_dir = Path(__file__).resolve().parent
    functions_dir = script_dir / "functions"

    step1_script = functions_dir / "generate_pool_nnt.py"
    step2_script = functions_dir / "build_rna_conflict_graphV2.py"
    step3_script = functions_dir / "select_from_conflict_graph.py"
    step4_script = functions_dir / "pool_rna_complement.py"

    for sp in (step1_script, step2_script, step3_script, step4_script):
        if not sp.exists():
            raise FileNotFoundError(f"Required script not found: {sp}")

    out_dir = Path.cwd() / f"Orthogonal_RNA_Pool_{args.num_nt}nt"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Final filenames requested by user.
    step1_final = f"RNA_Pool_{args.num_nt}nt.txt"
    step2_filtered_final = f"FilteredPool_{args.num_nt}nt.txt"
    step2_graph_final = f"ConflictGraph_{args.num_nt}nt.txt"
    step3_selected_final = "SelectedPool_from_graph.txt"
    step4_final = Path(args.output).name if args.output else f"Orthogonal_RNA_Pool_{args.num_nt}nt.txt"
    step4_figure = f"orthogonality_{args.num_nt}nt_RNA_Pool.png"

    # Intermediate names generated by existing scripts (they append '_out').
    step2_filtered_tmp = _add_suffix_to_path(step2_filtered_final, "_out")
    step2_graph_tmp = _add_suffix_to_path(step2_graph_final, "_out")
    step3_selected_tmp = _add_suffix_to_path(step3_selected_final, "_out")
    step4_tmp = _add_suffix_to_path(step3_selected_tmp, "_complement")

    print("=== Orthogonal KL Selection Pipeline ===", flush=True)
    print(f"Output folder: {out_dir}", flush=True)
    print(f"N: {args.num_nt}", flush=True)
    print(f"GC count: {args.gc_count}", flush=True)
    print(f"Rounds: {args.rounds}", flush=True)
    print(f"Guides: {', '.join(guides)}", flush=True)

    # Step 1
    cmd1 = [
        sys.executable,
        str(step1_script),
        str(args.num_nt),
        "--gc-count",
        str(args.gc_count),
        "--output",
        step1_final,
    ]
    _run(cmd1, out_dir)

    # Step 2
    cmd2 = [
        sys.executable,
        str(step2_script),
        "--num-nt",
        str(args.num_nt),
        "--input",
        step1_final,
        "--seq-out",
        step2_filtered_final,
        "--graph-out",
        step2_graph_final,
    ]
    for g in guides:
        cmd2.extend(["--guide", g])
    _run(cmd2, out_dir)

    # Step 3
    cmd3 = [
        sys.executable,
        str(step3_script),
        "--seq-file",
        step2_filtered_tmp,
        "--graph-file",
        step2_graph_tmp,
        "--rounds",
        str(args.rounds),
        "--output",
        step3_selected_final,
    ]
    _run(cmd3, out_dir)

    # Step 4
    cmd4 = [
        sys.executable,
        str(step4_script),
        step3_selected_tmp,
        "--output-figure",
        step4_figure,
    ]
    _run(cmd4, out_dir)

    # Rename intermediate '_out' files to requested final names.
    _replace_file(out_dir / step2_filtered_tmp, out_dir / step2_filtered_final)
    _replace_file(out_dir / step2_graph_tmp, out_dir / step2_graph_final)
    _replace_file(out_dir / step3_selected_tmp, out_dir / step3_selected_final)
    _replace_file(out_dir / step4_tmp, out_dir / step4_final)
    figure_path = out_dir / step4_figure
    if not figure_path.exists():
        print("WARNING: No NUPACK. Orthogonality figure was not generated.", flush=True)

    print("\n=== Done ===", flush=True)
    print(f"Generated files in: {out_dir}", flush=True)
    print(f"- {step1_final}", flush=True)
    print(f"- {step2_filtered_final}", flush=True)
    print(f"- {step2_graph_final}", flush=True)
    print(f"- {step3_selected_final}", flush=True)
    print(f"- {step4_final}", flush=True)
    if figure_path.exists():
        print(f"- {step4_figure}", flush=True)


def _run_gui(args: argparse.Namespace, guides: list[str]) -> int:
    """Collect parameters with PySide6 and run this script's CLI mode in the background."""
    from PySide6 import QtCore, QtGui, QtWidgets

    class SelectionWindow(QtWidgets.QWidget):
        """Keep the window open while a subprocess is using the output files."""

        def __init__(self) -> None:
            super().__init__()
            self.process: QtCore.QProcess | None = None

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:
            if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
                QtWidgets.QMessageBox.information(
                    self,
                    "Selection is running",
                    "The selection pipeline is still running. Wait for it to finish before closing.",
                )
                event.ignore()
                return
            event.accept()

    script_path = Path(__file__).resolve()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([str(script_path)])

    output_root = Path.cwd()
    window = SelectionWindow()
    window.setWindowTitle("Orthogonal RNA Sequence Selection")
    window.resize(760, 570)

    layout = QtWidgets.QVBoxLayout(window)
    intro = QtWidgets.QLabel(
        "Choose the KL-selection parameters, then run the four-step pipeline. "
        "The output folder is created in the current working directory. "
        "Sequence selection can take a long time; leave this window open until it finishes."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    form = QtWidgets.QFormLayout()

    def add_help_row(
        label: str, field: QtWidgets.QWidget, title: str, explanation: str
    ) -> None:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(field, 1)
        help_button = QtWidgets.QToolButton()
        help_button.setText("?")
        help_button.setAccessibleName(f"Help for {label}")
        help_button.setToolTip(f"Help for {label}")
        help_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        help_button.setFixedSize(26, 26)
        help_button.setStyleSheet(
            "QToolButton { background-color: #DDF3FF; color: #14557A; "
            "border: 1px solid #A5D7F0; border-radius: 13px; font-weight: bold; }"
            "QToolButton:hover { background-color: #BCE9FF; }"
        )
        help_button.clicked.connect(
            lambda checked=False: QtWidgets.QMessageBox.information(
                window, title, explanation
            )
        )
        row_layout.addWidget(help_button)
        form.addRow(label, row)

    num_nt = QtWidgets.QSpinBox()
    num_nt.setRange(4, max(99, args.num_nt))
    num_nt.setValue(max(4, args.num_nt))
    num_nt.setToolTip("KL sequence length. The generator requires at least 4 nt.")
    add_help_row(
        "KL length (N):",
        num_nt,
        "KL length (N)",
        "Length, in nucleotides, of each candidate KL sequence. The default is 9 "
        "and the minimum is 4. Larger values can make sequence generation and "
        "conflict-graph construction much slower.\n\nExample: N = 9 produces 9-nt KLs.",
    )

    gc_count = QtWidgets.QSpinBox()
    gc_count.setRange(2, max(2, num_nt.value() - 2))
    gc_count.setValue(args.gc_count)
    gc_count.setToolTip("Exact number of G/C bases in every generated KL sequence.")
    add_help_row(
        "GC count (C):",
        gc_count,
        "G/C base count (C)",
        "Exact number of G or C bases in each KL sequence; the other N-C bases "
        "are A or U. The default is 4. Choose between 2 and N-2 so A, U, G, "
        "and C can all appear. Counts other than 4 use generalized S/W patterns "
        "with the same sequence-level filters.\n\n"
        "Example: N = 9 and C = 5 yields five G/C and four A/U bases per KL.",
    )
    num_nt.valueChanged.connect(
        lambda value: gc_count.setMaximum(max(2, value - 2))
    )

    rounds = QtWidgets.QSpinBox()
    rounds.setRange(1, max(1_000_000, args.rounds))
    rounds.setValue(max(1, args.rounds))
    rounds.setToolTip("Number of randomized selection attempts in step 3.")
    add_help_row(
        "Selection rounds (R):",
        rounds,
        "Selection rounds (R)",
        "Number of randomized attempts used to find a large non-conflicting "
        "set in step 3. The default is 1000. More rounds may find a larger set, "
        "but take longer.\n\nExample: R = 2000 tries 2000 rounds.",
    )

    guide_edit = QtWidgets.QPlainTextEdit()
    guide_edit.setPlainText("\n".join(guides))
    guide_edit.setPlaceholderText("One RNA guide per line; commas or spaces also work")
    guide_edit.setMaximumHeight(92)
    add_help_row(
        "Guide RNA(s) (G):",
        guide_edit,
        "Guide RNA sequences (G)",
        "Candidate KLs that are too complementary to these guide sequences are "
        "filtered out in step 2. Use only A, C, G, and U. Enter one guide per "
        "line, or separate guides with commas or spaces.\n\n"
        "Default: CACGAAGUCAAUAC\nExample:\nCACGAAGUCAAUAC\nGGGAAAUUU",
    )

    output_edit = QtWidgets.QLineEdit(args.output or "")
    output_edit.setPlaceholderText("Orthogonal_RNA_Pool_<N>nt.txt (default)")
    output_edit.setToolTip("Optional final text filename; saved inside the output folder.")
    add_help_row(
        "Final filename (O):",
        output_edit,
        "Final output filename (O)",
        "Optional filename for the final RNA/complement text file in the output "
        "folder. Leave blank for Orthogonal_RNA_Pool_<N>nt.txt. This does not "
        "rename the orthogonality figure.\n\nExample: My_Final_Pool.txt",
    )
    layout.addLayout(form)

    folder_label = QtWidgets.QLabel()
    folder_label.setWordWrap(True)

    def update_folder_label() -> None:
        folder_label.setText(
            f"Output folder: {output_root / f'Orthogonal_RNA_Pool_{num_nt.value()}nt'}"
        )

    num_nt.valueChanged.connect(update_folder_label)
    update_folder_label()
    layout.addWidget(folder_label)

    controls = QtWidgets.QHBoxLayout()
    run_button = QtWidgets.QPushButton("Run selection")
    controls.addWidget(run_button)
    controls.addStretch()
    layout.addLayout(controls)

    status_label = QtWidgets.QLabel("Ready")
    layout.addWidget(status_label)
    log = QtWidgets.QPlainTextEdit()
    log.setReadOnly(True)
    log.setPlaceholderText("Pipeline output will appear here.")
    log.document().setMaximumBlockCount(10_000)
    layout.addWidget(log, 1)

    process = QtCore.QProcess(window)
    window.process = process
    process.setWorkingDirectory(str(output_root))
    process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
    environment = QtCore.QProcessEnvironment.systemEnvironment()
    environment.insert("PYTHONUNBUFFERED", "1")
    process.setProcessEnvironment(environment)

    def read_output() -> None:
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if chunk:
            log.moveCursor(QtGui.QTextCursor.MoveOperation.End)
            log.insertPlainText(chunk)
            log.ensureCursorVisible()

    process.readyReadStandardOutput.connect(read_output)

    def finished(exit_code: int, exit_status: QtCore.QProcess.ExitStatus) -> None:
        read_output()
        run_button.setEnabled(True)
        if exit_status == QtCore.QProcess.ExitStatus.NormalExit and exit_code == 0:
            status_label.setText("Completed successfully")
        else:
            status_label.setText(f"Failed (exit code {exit_code}); see log below")

    process.finished.connect(finished)

    def process_error(error: QtCore.QProcess.ProcessError) -> None:
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            run_button.setEnabled(True)
            status_label.setText(f"Could not start Python: {process.errorString()}")

    process.errorOccurred.connect(process_error)

    def start() -> None:
        if process.state() != QtCore.QProcess.ProcessState.NotRunning:
            return

        raw_guides = guide_edit.toPlainText().replace(",", " ").split()
        selected_guides = [guide.upper() for guide in raw_guides]
        if not selected_guides or any(set(guide) - set("ACGU") for guide in selected_guides):
            QtWidgets.QMessageBox.warning(
                window, "Invalid guides", "Enter at least one guide using only A, C, G, and U."
            )
            return

        output_name = output_edit.text().strip()
        if output_name and (
            Path(output_name).name != output_name or output_name in {".", ".."}
        ):
            QtWidgets.QMessageBox.warning(
                window, "Invalid filename", "Enter a filename, not a path."
            )
            return

        output_dir = output_root / f"Orthogonal_RNA_Pool_{num_nt.value()}nt"
        if output_dir.exists():
            answer = QtWidgets.QMessageBox.question(
                window,
                "Existing output folder",
                f"{output_dir} already exists. Running again may overwrite its files. Continue?",
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        command = [
            "--cli", "-N", str(num_nt.value()),
            "-C", str(gc_count.value()), "-R", str(rounds.value()),
        ]
        for guide in selected_guides:
            command.extend(["-G", guide])
        if output_name:
            command.extend(["-O", output_name])

        log.clear()
        status_label.setText("Running…")
        run_button.setEnabled(False)
        process.start(sys.executable, [str(script_path), *command])

    run_button.clicked.connect(start)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)

    if args.User:
        _print_user_instructions()
        return 0

    if args.gui or (not argv and not args.cli):
        try:
            return _run_gui(args, _normalize_guides(args.guide))
        except ModuleNotFoundError as exc:
            if exc.name != "PySide6":
                raise
            print(
                "GUI mode requires PySide6. Install it with 'pip install PySide6', "
                "or use --cli / other command-line options.",
                file=sys.stderr,
            )
            return 2

    _run_pipeline(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
