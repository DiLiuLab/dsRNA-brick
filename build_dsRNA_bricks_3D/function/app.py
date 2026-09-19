from __future__ import annotations

import math
import os
import sys
import textwrap
from html import escape
from pathlib import Path
from typing import Any


class _StderrFilter:
    """Filter noisy macOS framework lines while preserving real errors."""

    def __init__(self, raw, blocked_substrings: tuple[str, ...]) -> None:
        self._raw = raw
        self._blocked = blocked_substrings

    def write(self, data: str) -> int:
        try:
            if any(token in data for token in self._blocked):
                return len(data)
        except Exception:
            pass
        return self._raw.write(data)

    def flush(self) -> None:
        self._raw.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._raw, "isatty", lambda: False)())


# macOS stability tweaks for Qt + VTK embedding
if sys.platform == "darwin":
    os.environ.setdefault("QT_QPA_PLATFORM", "cocoa")
    # Qt 6 on macOS always uses layer-backing; this variable now only triggers warnings.
    os.environ.pop("QT_MAC_WANTS_LAYER", None)
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("VTK_USE_LEGACY_OPENGL", "1")
    # Suppress known benign macOS Text Services spam in terminal output.
    sys.stderr = _StderrFilter(
        sys.stderr,
        blocked_substrings=(
            "TSMSendMessageToUIServer: CFMessagePortSendRequest FAILED(-1)",
        ),
    )

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except Exception as exc:  # pragma: no cover
    QtCore = None
    QtGui = None
    QtWidgets = None
    _qt_import_error = exc
else:
    _qt_import_error = None

try:
    from .lattice_builder import (
        analyze_hemisphere_pairing,
        assign_kl_pool_pairs,
        build_lattice,
        missing_required_modules,
        relabel_tiles,
    )
    from .map2d import TileMapWidget, build_map_entries_by_z
    from .nupack_runner import run_nupack_design
    from .rna_tile_generator import generate_l1_tile_rna, generate_type2_tile_rna
    from .tile_registry import TileRegistry, default_tile_module_paths
    from .types import GlobalParams, TileSpec
    from .view3d import View3DWidget
except Exception as exc:  # pragma: no cover
    _app_import_error = exc
else:
    _app_import_error = None


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    mag = math.sqrt(x * x + y * y + z * z)
    if mag == 0:
        return (0.0, 0.0, 0.0)
    return (x / mag, y / mag, z / mag)


def default_params() -> GlobalParams:
    x_dir = (1.0, 0.0, 0.0)
    y_dir = (0.0, -1.0, 0.0)
    z_dir = (0.0, 0.0, -1.0)
    return GlobalParams(
        x_dir=x_dir,
        y_dir=y_dir,
        z_dir=z_dir,
        leftup=_normalize((1.0, 0.0, 1.0)),
        leftdown=_normalize((1.0, 0.0, -1.0)),
        rightup=_normalize((-1.0, 0.0, 1.0)),
        rightdown=_normalize((-1.0, 0.0, -1.0)),
        x_unit=1.5,
        y_unit=2.5,
        z_unit=2.5,
        diameter=0.4,
        radius_cylinder=0.2,
        radius_hemisphere=0.5,
        w_map_thickness=0.6,
    )


def _looks_like_rna(seq: str) -> bool:
    if not seq:
        return False
    for ch in seq.upper():
        if ch not in {"A", "U", "C", "G", "N"}:
            return False
    return True


def _count_kl_pairs_in_file(path: str) -> int:
    return len(_load_unique_kl_pairs(path))


def _load_unique_kl_pairs(path: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            cols = line.split()
            if len(cols) < 2:
                continue
            left = cols[0].strip().upper()
            right = cols[1].strip().upper()
            if not (_looks_like_rna(left) and _looks_like_rna(right)):
                continue
            pair = (left, right)
            if pair in seen:
                continue
            seen.add(pair)
            pairs.append(pair)
    return pairs


if QtCore is not None:
    class _NupackWorker(QtCore.QObject):  # type: ignore[misc]
        progress = QtCore.Signal(int, int, str, str)
        finished = QtCore.Signal(bool, object)

        def __init__(self, input_path: Path, output_path: Path) -> None:
            super().__init__()
            self._input_path = input_path
            self._output_path = output_path

        @QtCore.Slot()
        def run(self) -> None:
            try:
                result = run_nupack_design(
                    input_file=self._input_path,
                    output_file=self._output_path,
                    trials=3,
                    seed=42,
                    f_stop=0.02,
                    progress_cb=self._emit_progress,
                )
            except Exception as exc:
                self.finished.emit(False, str(exc))
                return
            self.finished.emit(True, result)

        def _emit_progress(self, current: int, total: int, tile_name: str, stage: str) -> None:
            self.progress.emit(current, total, tile_name, stage)
else:
    class _NupackWorker:  # pragma: no cover
        pass


class MainWindow(QtWidgets.QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("build_dsRNA_Bricks_3D")
        self.resize(1700, 950)

        self.params = default_params()
        module_paths = default_tile_module_paths(Path(__file__).resolve().parent)
        self.registry = TileRegistry(module_paths=module_paths, params=self.params)
        self.registry.reload()

        self._tiles: list[TileSpec] = []
        self._tile_by_id: dict[int, TileSpec] = {}
        self._tile_actor_by_id: dict[int, Any] = {}
        self._tile_selected: set[int] = set()
        self._tile_color: dict[int, str] = {}
        self._tile_label: dict[int, str] = {}
        self._tile_display: dict[int, tuple[int, int, int]] = {}
        self._map_widgets: dict[int, TileMapWidget] = {}
        self._last_nz: int = 0
        self._hemi_pair_lookup: dict[tuple[int, int], tuple[int, int]] = {}
        self._hemi_block_refs: set[tuple[int, int]] = set()
        self._tile_pair_count: dict[int, int] = {}
        self._tile_block_count: dict[int, int] = {}
        self._tile_links: dict[int, set[int]] = {}
        self._pairing_issues: list[str] = []
        self._lattice_pair_count: int = 0
        self._pool_pair_count: int | None = None
        self._assigned_seq_by_ref: dict[tuple[int, int], str] = {}
        self._assignment_output_path: Path | None = None
        self._nupack_output_path: Path | None = None
        self._nupack_thread: QtCore.QThread | None = None
        self._nupack_worker: _NupackWorker | None = None
        self._nupack_progress: QtWidgets.QProgressDialog | None = None
        self._nupack_show_finished_message: bool = True
        self._assignment_ready: bool = False
        self._alignment_error: str | None = None
        self._pipeline_outputs: tuple[Path, Path, Path] | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QtWidgets.QGroupBox("Inputs")
        grid = QtWidgets.QGridLayout(controls)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        self.pool_edit = QtWidgets.QLineEdit()
        self.pool_browse = QtWidgets.QPushButton("Browse...")
        self.pool_browse.clicked.connect(self._browse_pool)

        grid.addWidget(QtWidgets.QLabel("KL pool file:"), 0, 0)
        grid.addWidget(self.pool_edit, 0, 1, 1, 8)
        grid.addWidget(self.pool_browse, 0, 9)

        self.x_spin = QtWidgets.QSpinBox()
        self.x_spin.setRange(2, 999)
        self.x_spin.setValue(3)
        self.y_spin = QtWidgets.QSpinBox()
        self.y_spin.setRange(2, 999)
        self.y_spin.setValue(5)
        self.z_spin = QtWidgets.QSpinBox()
        self.z_spin.setRange(2, 999)
        self.z_spin.setValue(4)
        self.prefix_edit = QtWidgets.QLineEdit("Generated_Tiles")
        self.build_btn = QtWidgets.QPushButton("Build lattice")
        self.build_btn.clicked.connect(self._build_lattice)
        for spin in (self.x_spin, self.y_spin, self.z_spin):
            spin.setFixedWidth(70)

        x_label = QtWidgets.QLabel("X (cols, >=2):")
        y_label = QtWidgets.QLabel("Y (rows, >=2):")
        z_label = QtWidgets.QLabel("Z (layers, >=2):")
        for lbl in (x_label, y_label, z_label):
            lbl.setMinimumWidth(100)

        grid.addWidget(x_label, 1, 0)
        grid.addWidget(self.x_spin, 1, 1)
        grid.addWidget(y_label, 1, 2)
        grid.addWidget(self.y_spin, 1, 3)
        grid.addWidget(z_label, 1, 4)
        grid.addWidget(self.z_spin, 1, 5)
        grid.addWidget(QtWidgets.QLabel("Prefix:"), 1, 6)
        grid.addWidget(self.prefix_edit, 1, 7, 1, 2)

        grid.addWidget(self.build_btn, 1, 9)

        grid.setColumnStretch(8, 1)
        layout.addWidget(controls)

        content = QtWidgets.QHBoxLayout()

        self.view3d = View3DWidget(on_pick_tile=self._on_pick_tile)
        content.addWidget(self.view3d, stretch=1)

        side = QtWidgets.QFrame()
        side.setFrameShape(QtWidgets.QFrame.StyledPanel)
        side_layout = QtWidgets.QVBoxLayout(side)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(6)
        side.setMinimumWidth(440)

        self.selected_count_label = QtWidgets.QLabel("Selected tiles: 0")
        self.selected_count_label.setStyleSheet("font-weight: bold;")
        side_layout.addWidget(self.selected_count_label)

        self.selection_hint = QtWidgets.QLabel("Click a tile to select/unselect.")
        self.selection_hint.setStyleSheet("color: #555;")
        self.selection_hint.setWordWrap(True)
        side_layout.addWidget(self.selection_hint)

        self.btn_select_all = QtWidgets.QPushButton("Select all")
        self.btn_select_all.clicked.connect(self._select_all_tiles)
        self.btn_deselect_all = QtWidgets.QPushButton("Deselect all")
        self.btn_deselect_all.clicked.connect(self._deselect_all_tiles)
        side_layout.addWidget(self.btn_select_all)
        side_layout.addWidget(self.btn_deselect_all)

        side_layout.addWidget(QtWidgets.QLabel("XY maps (by Z layer):"))
        self.map_scroll = QtWidgets.QScrollArea()
        self.map_scroll.setWidgetResizable(True)
        self.map_container = QtWidgets.QWidget()
        self.map_layout = QtWidgets.QVBoxLayout(self.map_container)
        self.map_layout.setContentsMargins(4, 4, 4, 4)
        self.map_layout.setSpacing(6)
        self.map_scroll.setWidget(self.map_container)
        side_layout.addWidget(self.map_scroll, stretch=2)

        side_layout.addWidget(QtWidgets.QLabel("Selected tiles:"))
        self.selected_list = QtWidgets.QListWidget()
        side_layout.addWidget(self.selected_list, stretch=1)

        self.btn_generate = QtWidgets.QPushButton("Generate sequence")
        self.btn_generate.clicked.connect(self._generate_sequences)
        side_layout.addWidget(self.btn_generate)

        content.addWidget(side, stretch=0)
        layout.addLayout(content, stretch=1)

        self.status = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status)

    def _pair_ref_key(
        self,
        a: tuple[int, int],
        b: tuple[int, int],
    ) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    def _unique_hemi_pairs(self) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        unique: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for a, b in self._hemi_pair_lookup.items():
            key = self._pair_ref_key(a, b)
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        unique.sort(key=lambda p: (p[0][0], p[0][1], p[1][0], p[1][1]))
        return unique

    def _selected_internal_pairs_and_counts(
        self,
        selected_ids: set[int],
    ) -> tuple[list[tuple[tuple[int, int], tuple[int, int]]], dict[int, int]]:
        pair_list: list[tuple[tuple[int, int], tuple[int, int]]] = []
        paired_hemi_count: dict[int, int] = {tile_id: 0 for tile_id in selected_ids}
        for a_ref, b_ref in self._unique_hemi_pairs():
            a_tile = a_ref[0]
            b_tile = b_ref[0]
            if a_tile in selected_ids and b_tile in selected_ids and a_tile != b_tile:
                pair_list.append((a_ref, b_ref))
                paired_hemi_count[a_tile] = paired_hemi_count.get(a_tile, 0) + 1
                paired_hemi_count[b_tile] = paired_hemi_count.get(b_tile, 0) + 1
        return pair_list, paired_hemi_count

    def _selected_block_refs(
        self,
        selected_ids: set[int],
        selected_pairs: list[tuple[tuple[int, int], tuple[int, int]]],
    ) -> list[tuple[int, int]]:
        paired_refs: set[tuple[int, int]] = set()
        for a_ref, b_ref in selected_pairs:
            paired_refs.add(a_ref)
            paired_refs.add(b_ref)

        selected_refs: list[tuple[int, int]] = []
        for tile_id in sorted(selected_ids):
            tile = self._tile_by_id.get(tile_id)
            if tile is None:
                continue
            for hemi_idx in range(len(tile.hemi_positions)):
                ref = (tile_id, hemi_idx)
                if ref not in paired_refs:
                    selected_refs.append(ref)
        return selected_refs

    def _find_disconnected_selected_tiles(
        self,
        selected_ids: set[int],
        selected_pairs: list[tuple[tuple[int, int], tuple[int, int]]],
    ) -> list[int]:
        if len(selected_ids) <= 1:
            return []

        adjacency: dict[int, set[int]] = {tile_id: set() for tile_id in selected_ids}
        for a_ref, b_ref in selected_pairs:
            a_tile = a_ref[0]
            b_tile = b_ref[0]
            adjacency[a_tile].add(b_tile)
            adjacency[b_tile].add(a_tile)

        unseen = set(selected_ids)
        components: list[set[int]] = []
        while unseen:
            start = min(unseen)
            stack = [start]
            comp: set[int] = set()
            while stack:
                cur = stack.pop()
                if cur in comp:
                    continue
                comp.add(cur)
                for nxt in adjacency.get(cur, set()):
                    if nxt not in comp:
                        stack.append(nxt)
            components.append(comp)
            unseen -= comp

        if len(components) <= 1:
            return []

        components.sort(key=lambda c: (-len(c), min(c)))
        keep = components[0]
        wrong = sorted(set(selected_ids) - keep)
        return wrong

    def _wrong_tile_warning_text(self, title: str, tile_ids: list[int]) -> str:
        lines = [title]
        for tile_id in tile_ids:
            label = self._tile_label.get(tile_id, str(tile_id))
            lines.append(f"Wrong tile: {label}")
        return "\n".join(lines)

    def _ref_label(self, ref: tuple[int, int]) -> str:
        tile_id, hemi_idx = ref
        return f"{self._tile_label.get(tile_id, str(tile_id))}.h{hemi_idx + 1}"

    def _type2_c2_len(self, tile: TileSpec, ny: int) -> int | None:
        if tile.tile_name == "L_block_4":
            return 41
        if tile.tile_name == "W_block_2":
            return 16
        if tile.tile_name == "L_block_3":
            _x, _y, z = tile.lattice_pos
            # User rule:
            # - kz odd:  ny even -> 15, ny odd -> 16
            # - kz even: ny even -> 16, ny odd -> 15
            if z % 2 == 1:
                return 15 if (ny % 2 == 0) else 16
            return 16 if (ny % 2 == 0) else 15
        return None

    def _type1_c2_c3(self, tile: TileSpec) -> tuple[int, int] | None:
        """
        Type I c2/c3 mapping from sections 4.1, 4.2, 4.3, 5.1, 5.2, 5.3.
        """
        x, y, z = tile.lattice_pos

        # 5.1: W_seed_1
        # - set 1 (even z layers): c3=41, c2=16
        # - set 2 (odd z layers):  c3=40, c2=16
        if tile.tile_name == "W_seed_1":
            if z % 2 == 0:
                return (16, 41)
            return (16, 40)

        # 5.2: W_block_1 (both sets): c3=9, c2=9
        if tile.tile_name == "W_block_1":
            return (9, 9)

        # 5.3: W_1: c2=16, c3=16
        if tile.tile_name == "W_1":
            return (16, 16)

        # 4.2 / 4.3: L_1 tiles in z>0 layers.
        # Rule summary provided by user:
        # - one L_1 group: c2=c3=15
        # - the other L_1 group: c2=c3=16
        # In implementation this corresponds to x modulo class:
        #   x % 4 == 0 -> 15
        #   x % 4 == 2 -> 16
        if tile.tile_name == "L_1" and z > 0:
            if x % 4 == 0:
                return (15, 15)
            if x % 4 == 2:
                return (16, 16)
            return None

        # 4.1 rules are for z==0.
        if z != 0:
            return None

        # 4.1-1: L_block_1 at (0, even y, 0).
        if tile.tile_name == "L_block_1":
            return (9, 15)

        # 4.1-2: L_seed_1 at (1+4k, 0, 0).
        if tile.tile_name == "L_seed_1":
            return (90, 15)

        # 4.1-3 and 4.1-4: L_seed_2 two z=0 grids.
        if tile.tile_name == "L_seed_2":
            if y % 2 == 1 and x % 4 == 1:
                return (41, 16)
            if y % 2 == 0 and y >= 2 and x % 4 == 3:
                return (40, 15)
        return None

    @staticmethod
    def _format_tagged_text(tag: str, text: str, width: int = 120) -> list[str]:
        return textwrap.wrap(
            text,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
            initial_indent=f"{tag} ",
            subsequent_indent=" " * (len(tag) + 1),
        )

    def _tile_label_sort_key(self, tile_id: int) -> tuple[str, int, int]:
        label = self._tile_label.get(tile_id, str(tile_id))
        if len(label) > 1 and "_" in label:
            prefix = label[0]
            try:
                z_s, idx_s = label[1:].split("_", 1)
                return (prefix, int(z_s), int(idx_s))
            except Exception:
                pass
        return (label[:1], 9999, 9999)

    def _selected_tile_labels_ranked(self) -> list[str]:
        """
        Return labels in the same ordering used by the Selected tiles panel:
        all L first, then W, each sorted by numeric label key.
        """

        def label_key(lbl: str) -> tuple[int, int]:
            try:
                a_s, b_s = lbl[1:].split("_", 1)
                return (int(a_s), int(b_s))
            except Exception:
                return (9999, 9999)

        l_labels: list[str] = []
        w_labels: list[str] = []
        other_labels: list[str] = []
        for tile_id in self._tile_selected:
            label = self._tile_label.get(tile_id, str(tile_id))
            if label.startswith("L"):
                l_labels.append(label)
            elif label.startswith("W"):
                w_labels.append(label)
            else:
                other_labels.append(label)

        ranked = sorted(l_labels, key=label_key)
        ranked.extend(sorted(w_labels, key=label_key))
        ranked.extend(sorted(other_labels, key=label_key))
        return ranked

    def _prepare_lattice_sequence_assignment(self, pool_path: str) -> None:
        self._assigned_seq_by_ref.clear()
        self._assignment_ready = False
        self._alignment_error = None
        self._pool_pair_count = None

        if not pool_path:
            self._alignment_error = "Please select a KL pool file first.\nCannot generate sequence."
            return

        try:
            pool_pairs = _load_unique_kl_pairs(pool_path)
        except Exception as exc:
            self._alignment_error = f"Failed to read KL pool file: {exc}\nCannot generate sequence."
            return

        unique_pairs = self._unique_hemi_pairs()
        required = len(unique_pairs)
        available = len(pool_pairs)
        self._pool_pair_count = available
        if available < required:
            self._alignment_error = (
                f"The number of paired KL sequence ({available}) is not enough "
                f"for the lattice ({required}).\nCannot generate sequence."
            )
            return

        try:
            self._assigned_seq_by_ref.update(
                assign_kl_pool_pairs(unique_pairs, pool_pairs, self._tile_by_id)
            )
        except ValueError as exc:
            self._alignment_error = (
                f"KL sequence assignment failed: {exc}\nCannot generate sequence."
            )
            return

        self._assignment_ready = True

    def _generate_sequences(self) -> None:
        if not self._tiles:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate sequence",
                "Build lattice first before generating sequence.",
            )
            return

        selected_ids = set(self._tile_selected)
        if not selected_ids:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate sequence",
                "Select at least one tile first.",
            )
            return

        pool_path = self.pool_edit.text().strip()
        ny_now = int(self.y_spin.value())
        if not self._assignment_ready:
            self._prepare_lattice_sequence_assignment(pool_path)
        if not self._assignment_ready:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate sequence",
                self._alignment_error or "KL sequence alignment is not ready.\nCannot generate sequence.",
            )
            return

        selected_pairs, selected_paired_hemi_count = self._selected_internal_pairs_and_counts(selected_ids)
        not_closed_ids = [
            tile_id
            for tile_id in sorted(selected_ids)
            if selected_paired_hemi_count.get(tile_id, 0) < 2
        ]
        if not_closed_ids:
            msg = self._wrong_tile_warning_text("Structure is not closed.", not_closed_ids)
            QtWidgets.QMessageBox.warning(self, "Generate sequence", msg)
            return

        disconnected_ids = self._find_disconnected_selected_tiles(selected_ids, selected_pairs)
        if disconnected_ids:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate sequence",
                "Selected tiles are not connected.",
            )
            return

        required = len(selected_pairs)
        assignment_rows: list[tuple[str, str, str]] = []
        missing_pairs = 0
        selected_pair_refs: set[tuple[int, int]] = set()
        for a_ref, b_ref in selected_pairs:
            selected_pair_refs.add(a_ref)
            selected_pair_refs.add(b_ref)
            seq_a = self._assigned_seq_by_ref.get(a_ref)
            seq_b = self._assigned_seq_by_ref.get(b_ref)
            if seq_a is None or seq_b is None:
                missing_pairs += 1
                continue
            assignment_rows.append((self._ref_label(a_ref), self._ref_label(b_ref), f"{seq_a}\t{seq_b}"))

        if missing_pairs > 0:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate sequence",
                "KL sequence alignment is incomplete for selected pairs.\nCannot generate sequence.",
            )
            return

        # Type II sequence generation (currently for W_block_2, L_block_4, L_block_3).
        type2_missing_ids: list[int] = []
        type2_errors: list[str] = []
        type2_rows: list[tuple[str, str, int, str, str, str, str]] = []
        for tile_id in sorted(selected_ids, key=self._tile_label_sort_key):
            tile = self._tile_by_id.get(tile_id)
            if tile is None:
                continue
            c2_len = self._type2_c2_len(tile, ny_now)
            if c2_len is None:
                continue

            # In Type II, h2/h3 are KL-aligned 9-nt loops from hemisphere index 0/1.
            h2_ref = (tile_id, 0)
            h3_ref = (tile_id, 1)
            if h2_ref not in selected_pair_refs or h3_ref not in selected_pair_refs:
                type2_missing_ids.append(tile_id)
                continue

            h2_seq = self._assigned_seq_by_ref.get(h2_ref)
            h3_seq = self._assigned_seq_by_ref.get(h3_ref)
            if h2_seq is None or h3_seq is None:
                type2_errors.append(
                    f"{self._tile_label.get(tile_id, str(tile_id))}: missing KL sequence on h2/h3."
                )
                continue

            try:
                result = generate_type2_tile_rna(
                    c2_len=c2_len,
                    h2=h2_seq,
                    h3=h3_seq,
                    seed=42 + tile_id,
                )
            except Exception as exc:
                type2_errors.append(f"{self._tile_label.get(tile_id, str(tile_id))}: {exc}")
                continue

            type2_rows.append(
                (
                    self._tile_label.get(tile_id, str(tile_id)),
                    tile.tile_name,
                    c2_len,
                    h2_seq,
                    h3_seq,
                    result.sequence_spaced,
                    result.structure_spaced,
                )
            )

        if type2_missing_ids:
            msg = self._wrong_tile_warning_text("Structure is not closed.", sorted(type2_missing_ids))
            QtWidgets.QMessageBox.warning(self, "Generate sequence", msg)
            return
        if type2_errors:
            msg = "Type II sequence generation failed.\n" + "\n".join(type2_errors[:12])
            QtWidgets.QMessageBox.warning(self, "Generate sequence", msg)
            return

        # Type I generation for sections 4.1 / 4.2 / 4.3 / 5.1 / 5.2 / 5.3 mapping.
        type1_errors: list[str] = []
        type1_rows: list[tuple[str, str, int, int, str, str, str]] = []
        for tile_id in sorted(selected_ids, key=self._tile_label_sort_key):
            tile = self._tile_by_id.get(tile_id)
            if tile is None:
                continue
            c2_c3 = self._type1_c2_c3(tile)
            if c2_c3 is None:
                continue
            c2_len, c3_len = c2_c3
            h_loop: dict[str, str] = {}
            blocked_h: set[str] = set()
            # Type I hemisphere mapping:
            # h1 -> upper-left (index 0), h2 -> lower-left (index 1).
            h_idx = {"h1": 0, "h2": 1, "h3": 2, "h4": 3}
            block_override = {
                "h1": "GUAA",
                "h2": "UUCG",
                "h3": "AAUAAUA",
                "h4": "AAUAAUA",
            }
            for h_name, hemi_idx in h_idx.items():
                ref = (tile_id, hemi_idx)
                if ref in selected_pair_refs:
                    seq = self._assigned_seq_by_ref.get(ref)
                    if seq is None:
                        type1_errors.append(
                            f"{self._tile_label.get(tile_id, str(tile_id))}: missing KL sequence at {h_name}."
                        )
                        seq = ""
                    h_loop[h_name] = seq
                else:
                    blocked_h.add(h_name)
                    h_loop[h_name] = block_override[h_name]

            if type1_errors:
                continue

            # Type I blocked-loop length overrides requested by design rules.
            if "h1" in blocked_h:
                c3_len = 9
            if "h2" in blocked_h:
                c2_len = 9
            drop_h4_c3 = "h1" in blocked_h and "h4" in blocked_h
            if drop_h4_c3:
                c3_len = 0

            try:
                result = generate_l1_tile_rna(
                    c1_len=25,
                    c2_len=c2_len,
                    c3_len=c3_len,
                    h1=h_loop["h1"],
                    h2=h_loop["h2"],
                    h3=h_loop["h3"],
                    h4=h_loop["h4"],
                    seed=42 + tile_id,
                    blocked_h=blocked_h,
                    drop_h4_c3=drop_h4_c3,
                )
            except Exception as exc:
                type1_errors.append(f"{self._tile_label.get(tile_id, str(tile_id))}: {exc}")
                continue

            blocked_txt = ",".join(sorted(blocked_h)) if blocked_h else "none"
            type1_rows.append(
                (
                    self._tile_label.get(tile_id, str(tile_id)),
                    tile.tile_name,
                    c2_len,
                    c3_len,
                    blocked_txt,
                    result.sequence_spaced,
                    result.structure_spaced,
                )
            )

        if type1_errors:
            msg = "Type I sequence generation failed.\n" + "\n".join(type1_errors[:12])
            QtWidgets.QMessageBox.warning(self, "Generate sequence", msg)
            return

        compact_map: dict[str, tuple[str, str]] = {}
        for label, _tile_name, _c2_len, _h2, _h3, seq_line, ss_line in type2_rows:
            compact_map[label] = (seq_line, ss_line)
        for label, _tile_name, _c2_len, _c3_len, _blocked, seq_line, ss_line in type1_rows:
            compact_map[label] = (seq_line, ss_line)

        compact_rows: list[tuple[str, str, str]] = []
        for label in self._selected_tile_labels_ranked():
            pair = compact_map.get(label)
            if pair is None:
                continue
            compact_rows.append((label, pair[0], pair[1]))

        prefix = self.prefix_edit.text().strip() or "Generated_Tiles"
        base_dir = Path.cwd()
        tile_structure_path = base_dir / f"{prefix}_tile_structure.txt"
        svg_path = base_dir / f"{prefix}_2D_map.svg"
        sequence_path = base_dir / f"{prefix}_sequence.txt"
        self._assignment_output_path = tile_structure_path
        self._pipeline_outputs = (tile_structure_path, svg_path, sequence_path)

        with open(tile_structure_path, "w", encoding="utf-8") as fh:
            for label, seq_line, ss_line in compact_rows:
                fh.write(f"\n*******TILE_{label}*******\n")
                fh.write(f"{seq_line}\n")
                fh.write(f"{ss_line}\n")

        svg_written = self._export_2d_svg(out_path=svg_path, show_dialog=False)
        if svg_written is None:
            return

        self._refresh_selected_list()
        type2_count = len(type2_rows)
        type1_count = len(type1_rows)
        self.status.setText(
            f"Generated tile structure + 2D map. Starting NUPACK... "
            f"({required} selected pairs, {type2_count} Type II tiles, "
            f"{type1_count} Type I tiles)."
        )
        self._run_nupack_design(
            in_path=tile_structure_path,
            out_path=sequence_path,
            show_finished_message=False,
        )

    def _run_nupack_design(
        self,
        in_path: Path | None = None,
        out_path: Path | None = None,
        show_finished_message: bool = True,
    ) -> None:
        if in_path is None:
            in_path = self._assignment_output_path
        if in_path is None or not in_path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Run NUPACK design",
                "Generate sequence first. Input sequence file is missing.",
            )
            return
        if self._nupack_thread is not None and self._nupack_thread.isRunning():
            QtWidgets.QMessageBox.information(
                self,
                "Run NUPACK design",
                "NUPACK design is already running.",
            )
            return

        if out_path is None:
            out_path = in_path.with_name(in_path.stem + "_nupack_output.txt")
        self._nupack_show_finished_message = show_finished_message
        self.status.setText("Running NUPACK design...")

        progress = QtWidgets.QProgressDialog("Preparing NUPACK run...", "", 0, 0, self)
        progress.setWindowTitle("NUPACK design")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()
        self._nupack_progress = progress

        thread = QtCore.QThread(self)
        worker = _NupackWorker(in_path, out_path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_nupack_progress)
        worker.finished.connect(self._on_nupack_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._nupack_thread = thread
        self._nupack_worker = worker
        self.btn_generate.setEnabled(False)
        self.build_btn.setEnabled(False)
        thread.start()

    def _on_nupack_progress(self, current: int, total: int, tile_name: str, stage: str) -> None:
        dialog = self._nupack_progress
        if dialog is None:
            return
        if total <= 0:
            dialog.setRange(0, 0)
            return
        if dialog.maximum() != total:
            dialog.setRange(0, total)
        if stage == "init":
            dialog.setLabelText(f"Preparing NUPACK run ({total} tiles)...")
        elif stage == "start":
            dialog.setLabelText(f"Running NUPACK: {tile_name} ({current + 1}/{total})")
        else:
            dialog.setLabelText(f"Completed {current}/{total}: {tile_name}")
        dialog.setValue(max(0, min(current, total)))

    def _on_nupack_finished(self, ok: bool, payload: object) -> None:
        dialog = self._nupack_progress
        self._nupack_progress = None
        if dialog is not None:
            dialog.setValue(dialog.maximum())
            dialog.close()

        self._nupack_thread = None
        self._nupack_worker = None
        self.btn_generate.setEnabled(True)
        self.build_btn.setEnabled(True)

        if not ok:
            self._pipeline_outputs = None
            self.status.setText("NUPACK design failed.")
            QtWidgets.QMessageBox.warning(
                self,
                "Run NUPACK design",
                f"NUPACK design failed:\n{payload}",
            )
            return

        result = payload
        self._nupack_output_path = result.output_path
        self.status.setText("NUPACK design finished.")
        outputs = self._pipeline_outputs
        if outputs is not None:
            tile_structure_path, svg_path, sequence_path = outputs
            self._pipeline_outputs = None
            QtWidgets.QMessageBox.information(
                self,
                "Generate sequence",
                "NUPACK design finished.\n\n"
                "Generated files in the current folder:\n"
                f"- {tile_structure_path.name}\n"
                f"- {svg_path.name}\n"
                f"- {sequence_path.name}",
            )
        elif self._nupack_show_finished_message:
            QtWidgets.QMessageBox.information(
                self,
                "Run NUPACK design",
                "NUPACK design finished.",
            )

    def _browse_pool(self) -> None:
        dialog = QtWidgets.QFileDialog(self, "Select KL pool file", str(Path.home()))
        dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dialog.setNameFilters(["Text files (*.txt)", "All files (*.*)"])
        dialog.selectNameFilter("Text files (*.txt)")
        # Native dialogs can be unstable with embedded VTK/Qt on macOS.
        dialog.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        dialog.setOption(QtWidgets.QFileDialog.ReadOnly, True)

        self.view3d.setEnabled(False)
        try:
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                selected = dialog.selectedFiles()
                if selected:
                    self.pool_edit.setText(selected[0])
                    if self._tiles:
                        self._prepare_lattice_sequence_assignment(selected[0])
        finally:
            self.view3d.setEnabled(True)
            self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._nupack_thread is not None and self._nupack_thread.isRunning():
            QtWidgets.QMessageBox.warning(
                self,
                "NUPACK design running",
                "Please wait for NUPACK design to finish before closing the app.",
            )
            event.ignore()
            return
        self.view3d.close_plotter()
        super().closeEvent(event)

    def _clear_map_widgets(self) -> None:
        for i in reversed(range(self.map_layout.count())):
            item = self.map_layout.takeAt(i)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _clear_state(self) -> None:
        self.view3d.clear_scene()
        self._tiles.clear()
        self._tile_by_id.clear()
        self._tile_actor_by_id.clear()
        self._tile_color.clear()
        self._map_widgets.clear()
        self._tile_selected.clear()
        self._tile_label.clear()
        self._tile_display.clear()
        self._hemi_pair_lookup.clear()
        self._hemi_block_refs.clear()
        self._tile_pair_count.clear()
        self._tile_block_count.clear()
        self._tile_links.clear()
        self._pairing_issues.clear()
        self._lattice_pair_count = 0
        self._pool_pair_count = None
        self._assigned_seq_by_ref.clear()
        self._assignment_output_path = None
        self._nupack_output_path = None
        self._nupack_show_finished_message = True
        self._assignment_ready = False
        self._alignment_error = None
        self._pipeline_outputs = None
        self.selected_list.clear()
        self.selected_count_label.setText("Selected tiles: 0")
        self._clear_map_widgets()

    def _build_lattice(self) -> None:
        nx = int(self.x_spin.value())
        ny = int(self.y_spin.value())
        nz = int(self.z_spin.value())
        prefix = self.prefix_edit.text().strip() or "Generated_Tiles"
        pool = self.pool_edit.text().strip()

        self.registry.reload()

        if nx < 2 or ny < 2 or nz < 2:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid lattice size",
                "Constraints:\n  - X, Y, Z must be integers >= 2",
            )
            return

        missing = missing_required_modules(self.registry.modules)
        if missing:
            self.status.setText("Missing required tile modules: " + ", ".join(missing))
            return

        self._clear_state()
        self._last_nz = nz

        result = build_lattice(nx=nx, ny=ny, nz=nz, modules=self.registry.modules, params=self.params)
        self._tiles = result.tiles
        self._tile_by_id = {tile.tile_id: tile for tile in self._tiles}

        pairing = analyze_hemisphere_pairing(self._tiles)
        self._hemi_pair_lookup = pairing["pair_lookup"]
        self._hemi_block_refs = pairing["block_refs"]
        self._tile_pair_count = pairing["tile_pair_count"]
        self._tile_block_count = pairing["tile_block_count"]
        self._tile_links = pairing["tile_links"]
        self._pairing_issues = pairing["issues"]
        self._lattice_pair_count = int(pairing["pair_count"])

        for tile in self._tiles:
            actor = self.view3d.add_tile(tile, opacity=0.35, pickable=True)
            self._tile_actor_by_id[tile.tile_id] = actor
            self._tile_color[tile.tile_id] = tile.color

        self._tile_label, self._tile_display = relabel_tiles(self._tiles)
        self._prepare_lattice_sequence_assignment(pool)
        self._build_2d_maps()
        self.view3d.finalize_view()

        msg = f"Lattice: {nx} x {ny} x {nz} | Prefix: {prefix}"
        if pool:
            msg += f" | Pool: {Path(pool).name}"
        else:
            msg += " | Pool: (none)"
        self.status.setText(msg)

    def _on_pick_tile(self, tile_id: int | None) -> None:
        if tile_id is None:
            return
        if tile_id not in self._tile_actor_by_id:
            return
        self._toggle_tile(tile_id)

    def _set_tile_selected(self, tile_id: int, selected: bool) -> None:
        actor = self._tile_actor_by_id.get(tile_id)
        if actor is None:
            return
        if selected:
            self._tile_selected.add(tile_id)
            self.view3d.set_actor_opacity(actor, 1.0)
        else:
            self._tile_selected.discard(tile_id)
            self.view3d.set_actor_opacity(actor, 0.35)

    def _toggle_tile(self, tile_id: int) -> None:
        self._set_tile_selected(tile_id, tile_id not in self._tile_selected)
        self._refresh_selected_list()
        self._update_maps()
        self.view3d.render()

    def _select_all_tiles(self) -> None:
        for tile_id in list(self._tile_actor_by_id.keys()):
            self._set_tile_selected(tile_id, True)
        self._refresh_selected_list()
        self._update_maps()
        self.view3d.render()

    def _deselect_all_tiles(self) -> None:
        for tile_id in list(self._tile_actor_by_id.keys()):
            self._set_tile_selected(tile_id, False)
        self._refresh_selected_list()
        self._update_maps()
        self.view3d.render()

    def _get_tile_color(self, tile_id: int) -> str:
        return self._tile_color.get(tile_id, "#cccccc")

    def _is_tile_selected(self, tile_id: int) -> bool:
        return tile_id in self._tile_selected

    def _build_2d_maps(self) -> None:
        self._clear_map_widgets()
        self._map_widgets.clear()
        if self._last_nz <= 0:
            return

        by_z = build_map_entries_by_z(self._tiles, self.params)
        for z in reversed(range(self._last_nz)):
            widget = TileMapWidget(
                z_layer=z,
                on_tile_click=self._toggle_tile,
                get_tile_color=self._get_tile_color,
                is_selected=self._is_tile_selected,
            )
            widget.set_entries(by_z.get(z, []))
            self.map_layout.addWidget(widget)
            self._map_widgets[z] = widget

        self.map_layout.addStretch(1)

    @staticmethod
    def _map_entry_bounds(entries: list[Any]) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for entry in entries:
            if entry.poly:
                for x, y in entry.poly:
                    xs.append(float(x))
                    ys.append(float(y))
            elif entry.rect:
                cx, cy, w, h = entry.rect
                xs.extend([float(cx - w / 2.0), float(cx + w / 2.0)])
                ys.extend([float(cy - h / 2.0), float(cy + h / 2.0)])
        if not xs or not ys:
            return None
        return (min(xs), max(xs), min(ys), max(ys))

    def _export_2d_svg(
        self,
        out_path: Path | None = None,
        show_dialog: bool = True,
    ) -> Path | None:
        if not self._tiles:
            QtWidgets.QMessageBox.warning(
                self,
                "Export 2D SVG",
                "Build lattice first.",
            )
            return None

        by_z = build_map_entries_by_z(self._tiles, self.params)
        zs = sorted(by_z.keys(), reverse=True)
        if not zs:
            QtWidgets.QMessageBox.warning(
                self,
                "Export 2D SVG",
                "No 2D map entries to export.",
            )
            return None

        if out_path is None:
            pool_path = self.pool_edit.text().strip()
            if pool_path:
                base_dir = Path(pool_path).resolve().parent
            elif self._assignment_output_path is not None:
                base_dir = self._assignment_output_path.resolve().parent
            else:
                base_dir = Path.cwd()
            prefix = self.prefix_edit.text().strip() or "Generated_Tiles"
            out_path = base_dir / f"{prefix}_2D_map.svg"

        # Export-only scaling requested by user:
        # Keep canvas scale stable.
        x_unit_scale = 9.0
        y_unit_scale = 3.0
        z_unit_scale = 0.5
        # Draw rule: multiply map x-coordinates by 2 for all tiles.
        draw_x_scale = 2.0

        margin = 24.0
        layer_h = 280.0 * y_unit_scale
        layer_gap = 20.0 * z_unit_scale
        y_axis_gap = 10.0
        y_label_space = 44.0
        side_gap = 16.0
        pad_left = y_label_space + y_axis_gap + side_gap
        pad_right = side_gap
        pad_top = 42.0
        pad_bottom = 14.0

        # Size canvas width from geometry bounds so left/right margins stay tight.
        max_span_x = 1.0
        max_span_y = 1.0
        for z in zs:
            bounds_z = self._map_entry_bounds(by_z.get(z, []))
            if bounds_z is None:
                continue
            bx0, bx1, by0, by1 = bounds_z
            bx0 *= draw_x_scale
            bx1 *= draw_x_scale
            max_span_x = max(max_span_x, bx1 - bx0)
            max_span_y = max(max_span_y, by1 - by0)
        avail_h = max(1.0, layer_h - pad_top - pad_bottom)
        scale_from_h = avail_h / max(1e-6, max_span_y)
        layer_w = pad_left + pad_right + max_span_x * scale_from_h
        canvas_w = int(layer_w + 2 * margin)
        canvas_h = int(2 * margin + len(zs) * layer_h + (len(zs) - 1) * layer_gap)
        show_frame_guides = False

        # Sequence labels for loops/bulges shown inside each tile box.
        type2_names = {"L_block_3", "L_block_4", "W_block_2"}
        h_order = {"h4": 0, "h1": 1, "h3": 2, "h2": 3}

        # Real block-sequence rules:
        # Type I (4-loop tiles): h1=GUAA, h2=UUCG, h3=AAUAAUA, h4=AAUAAUA
        # Type II fallback (3-loop tiles): h4 fixed UUCG, h3/h2 use block motifs.
        type1_block_seq = {
            "h1": "GUAA",
            "h2": "UUCG",
            "h3": "AAUAAUA",
            "h4": "AAUAAUA",
        }
        type2_block_seq = {
            "h2": "GUAA",
            "h3": "AAUAAUA",
            "h4": "UUCG",
        }

        def hemi_index_map(tile: TileSpec) -> list[tuple[str, int]]:
            if tile.tile_name in type2_names:
                return [("h2", 0), ("h3", 1), ("h4", 2)]
            if len(tile.hemi_positions) >= 4:
                return [("h1", 0), ("h2", 1), ("h3", 2), ("h4", 3)]
            return [(f"h{i+1}", i) for i in range(len(tile.hemi_positions))]

        tile_seq_map: dict[int, dict[str, str]] = {}
        tile_hz_map: dict[int, dict[str, int]] = {}
        tile_by_id: dict[int, TileSpec] = {tile.tile_id: tile for tile in self._tiles}
        ny_now = int(self.y_spin.value())
        for tile in self._tiles:
            seq_map: dict[str, str] = {}
            hz_map: dict[str, int] = {}
            for h_name, hemi_idx in hemi_index_map(tile):
                if hemi_idx >= len(tile.hemi_positions):
                    continue
                ref = (tile.tile_id, hemi_idx)
                seq = self._assigned_seq_by_ref.get(ref)
                if seq is None:
                    if ref in self._hemi_pair_lookup:
                        seq = "UNASSIGNED"
                    else:
                        if tile.tile_name in type2_names:
                            seq = type2_block_seq.get(h_name, "AAUAAUA")
                        else:
                            seq = type1_block_seq.get(h_name, "AAUAAUA")
                seq_map[h_name] = seq
                hz_map[h_name] = int(round(tile.hemi_positions[hemi_idx][2] / self.params.z_unit))
            tile_seq_map[tile.tile_id] = seq_map
            tile_hz_map[tile.tile_id] = hz_map

        def l_seq_lines(tile_id: int) -> list[str]:
            seq_map = tile_seq_map.get(tile_id, {})
            if "h1" in seq_map and "h2" in seq_map and "h3" in seq_map and "h4" in seq_map:
                return [f"{seq_map['h4']}/{seq_map['h1']}", f"{seq_map['h3']}/{seq_map['h2']}"]
            if "h4" in seq_map and "h3" in seq_map and "h2" in seq_map:
                return [seq_map["h4"], f"{seq_map['h3']}/{seq_map['h2']}"]
            vals = [seq_map[k] for k in sorted(seq_map.keys(), key=lambda k: h_order.get(k, 99))]
            if len(vals) <= 1:
                return vals
            return ["/".join(vals[:2]), "/".join(vals[2:])] if len(vals) > 2 else ["/".join(vals)]

        def bb_text(n: int | None) -> str:
            return f"BBBB{n}BBBB" if n is not None else ""

        def text_center_y(y: float, font_size: float) -> float:
            # Mac/SVG viewers often render text a bit high even with dominant-baseline.
            # Apply a small visual offset so labels sit in the line center.
            return y + font_size * 0.30

        def fit_mid_text_x(
            left_x: float,
            left_text: str,
            right_x: float,
            right_text: str,
            preferred_mid_x: float,
            mid_text: str,
            char_px: float,
            min_gap: float = 10.0,
        ) -> tuple[float, bool]:
            """
            Keep center text from overlapping left/right labels on the same line.
            left_x/right_x are anchors used by start/end text respectively.
            """
            if not mid_text:
                return (preferred_mid_x, True)
            left_w = len(left_text) * char_px
            right_w = len(right_text) * char_px
            mid_w = len(mid_text) * char_px
            left_end = left_x + left_w
            right_start = right_x - right_w
            min_mid = left_end + min_gap + mid_w / 2.0
            max_mid = right_start - min_gap - mid_w / 2.0
            if min_mid <= max_mid:
                return (max(min_mid, min(preferred_mid_x, max_mid)), True)
            # If not enough room, keep near geometric center of remaining span.
            return ((left_end + right_start) / 2.0, False)

        seq_font_family = "Courier New, Courier, monospace"
        anno_font_family = seq_font_family

        def x_span_at_y(poly_points: list[tuple[float, float]], y_val: float) -> tuple[float, float]:
            if not poly_points:
                return (0.0, 0.0)
            xs: list[float] = []
            eps = 1e-6
            n = len(poly_points)
            for i in range(n):
                x1, y1 = poly_points[i]
                x2, y2 = poly_points[(i + 1) % n]
                if abs(y1 - y2) < eps:
                    if abs(y_val - y1) <= eps:
                        xs.extend([x1, x2])
                    continue
                y_lo = min(y1, y2) - eps
                y_hi = max(y1, y2) + eps
                if y_val < y_lo or y_val > y_hi:
                    continue
                t = (y_val - y1) / (y2 - y1)
                if t < -eps or t > 1.0 + eps:
                    continue
                xs.append(x1 + t * (x2 - x1))
            if not xs:
                x_vals = [p[0] for p in poly_points]
                return (min(x_vals), max(x_vals))
            xs.sort()
            uniq: list[float] = []
            for x in xs:
                if not uniq or abs(x - uniq[-1]) > 1e-5:
                    uniq.append(x)
            if len(uniq) == 1:
                return (uniq[0], uniq[0])
            return (uniq[0], uniq[-1])

        def to_screen(
            x_u: float,
            y_u: float,
            x_min: float,
            x_max: float,
            y_min: float,
            y_max: float,
            layer_y0: float,
        ) -> tuple[float, float]:
            span_x = max(1e-6, x_max - x_min)
            span_y = max(1e-6, y_max - y_min)
            avail_w = layer_w - pad_left - pad_right
            avail_h = layer_h - pad_top - pad_bottom
            scale = min(avail_w / span_x, avail_h / span_y)
            used_w = span_x * scale
            used_h = span_y * scale
            off_x = margin + pad_left
            off_y = layer_y0 + pad_top + (avail_h - used_h) / 2.0
            sx = off_x + (x_u - x_min) * scale
            sy = off_y + (y_max - y_u) * scale
            return sx, sy

        svg: list[str] = []
        svg.append('<?xml version="1.0" encoding="UTF-8"?>')
        svg.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w}" height="{canvas_h}" '
            f'viewBox="0 0 {canvas_w} {canvas_h}">'
        )
        svg.append('<rect x="0" y="0" width="100%" height="100%" fill="#f7f7f7"/>')

        for layer_i, z in enumerate(zs):
            entries = by_z.get(z, [])
            y0 = margin + layer_i * (layer_h + layer_gap)
            svg.append(
                f'<rect x="{margin:.1f}" y="{y0:.1f}" width="{layer_w:.1f}" height="{layer_h:.1f}" '
                f'fill="#ffffff" stroke="#dddddd" stroke-width="1"/>'
            )
            # Keep layer label at top-left; offset to avoid y-label overlap.
            svg.append(
                f'<text x="{(margin + 1):.1f}" y="{(y0 + 10):.1f}" '
                f'font-family="Arial, sans-serif" font-size="17" fill="#333333">Layer Z = {z}</text>'
            )

            bounds = self._map_entry_bounds(entries)
            if bounds is None:
                continue
            x_min, x_max, y_min, y_max = bounds
            x_min *= draw_x_scale
            x_max *= draw_x_scale

            # y-axis labels on the left side.
            y_tick_min = int(math.floor(y_min))
            y_tick_max = int(math.ceil(y_max))
            left_shape_x, _ = to_screen(float(x_min), float(y_min), x_min, x_max, y_min, y_max, y0)
            x_axis = left_shape_x - y_axis_gap
            for yv in range(y_tick_min, y_tick_max + 1):
                _tx, ty = to_screen(float(x_min), float(yv), x_min, x_max, y_min, y_max, y0)
                svg.append(
                    f'<line x1="{x_axis - 4:.2f}" y1="{ty:.2f}" x2="{x_axis + 4:.2f}" y2="{ty:.2f}" '
                    f'stroke="#888888" stroke-width="1"/>'
                )
                svg.append(
                    f'<text x="{(x_axis - 1):.2f}" y="{(ty + 4):.2f}" text-anchor="end" '
                    f'font-family="Arial, sans-serif" font-size="13" fill="#666666">y={yv}</text>'
                )

            for entry in entries:
                fill = self._tile_color.get(entry.tile_id, "#cccccc")
                label = self._tile_label.get(entry.tile_id, str(entry.tile_id))
                tile_obj = tile_by_id.get(entry.tile_id)
                c2_len: int | None = None
                c3_len: int | None = None
                if tile_obj is not None:
                    type1_lengths = self._type1_c2_c3(tile_obj)
                    if type1_lengths is not None:
                        c2_len, c3_len = type1_lengths
                    else:
                        type2_c2 = self._type2_c2_len(tile_obj, ny_now)
                        if type2_c2 is not None:
                            c2_len = type2_c2
                cx_s = 0.0
                cy_s = 0.0
                w_s = 0.0
                h_s = 0.0
                shape_left = 0.0
                shape_right = 0.0
                shape_top = 0.0
                shape_bottom = 0.0
                is_l_triangle = False
                l_poly_points: list[tuple[float, float]] = []

                if entry.kind == "L" and entry.poly:
                    points: list[tuple[float, float]] = []
                    for x_u, y_u in entry.poly:
                        sx, sy = to_screen(float(x_u) * draw_x_scale, float(y_u), x_min, x_max, y_min, y_max, y0)
                        points.append((sx, sy))
                    if points:
                        l_poly_points = points[:]
                        pts_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
                        svg.append(
                            f'<polygon points="{pts_text}" fill="{fill}" fill-opacity="0.92" stroke="none"/>'
                        )
                        cx_s = sum(p[0] for p in points) / len(points)
                        cy_s = sum(p[1] for p in points) / len(points)
                        xs_poly = [p[0] for p in points]
                        ys_poly = [p[1] for p in points]
                        shape_left = min(xs_poly)
                        shape_right = max(xs_poly)
                        shape_top = min(ys_poly)
                        shape_bottom = max(ys_poly)
                        is_l_triangle = len(points) == 3
                elif entry.rect:
                    cx_u, cy_u, w_u, h_u = entry.rect
                    x1, y1 = to_screen(
                        float(cx_u - w_u / 2.0) * draw_x_scale,
                        float(cy_u - h_u / 2.0),
                        x_min,
                        x_max,
                        y_min,
                        y_max,
                        y0,
                    )
                    x2, y2 = to_screen(
                        float(cx_u + w_u / 2.0) * draw_x_scale,
                        float(cy_u + h_u / 2.0),
                        x_min,
                        x_max,
                        y_min,
                        y_max,
                        y0,
                    )
                    left = min(x1, x2)
                    top = min(y1, y2)
                    w_s = abs(x2 - x1)
                    h_s = abs(y2 - y1)
                    cx_s = (x1 + x2) / 2.0
                    cy_s = (y1 + y2) / 2.0
                    shape_left = left
                    shape_right = left + w_s
                    shape_top = top
                    shape_bottom = top + h_s
                    svg.append(
                        f'<rect x="{left:.2f}" y="{top:.2f}" width="{w_s:.2f}" height="{h_s:.2f}" '
                        f'fill="{fill}" fill-opacity="0.92" stroke="none"/>'
                    )

                if cx_s > 0.0:
                    if entry.kind == "L" and shape_right > shape_left and shape_bottom > shape_top:
                        seq_map = tile_seq_map.get(entry.tile_id, {})
                        h1_seq = seq_map.get("h1", "")
                        h4_seq = seq_map.get("h4", "")
                        h2_seq = seq_map.get("h2", "")
                        low_right_seq = seq_map.get("h3", "")

                        rows = 3 if is_l_triangle else 5
                        frame_left = shape_left
                        frame_right = shape_right
                        frame_top = shape_top
                        frame_bottom = shape_bottom
                        frame_h = max(1.0, frame_bottom - frame_top)
                        row_h = frame_h / rows
                        frame_pad_x = max(4.0, min(18.0, (frame_right - frame_left) * 0.03))
                        top_line_y = frame_top + row_h * 0.5
                        low_line_y = frame_bottom - row_h * 0.5
                        # Middle line center: row 3 of 5, row 2 of 3.
                        name_y = frame_top + row_h * (2.5 if rows == 5 else 1.5)
                        top_line_y_12 = text_center_y(top_line_y, 14.0)
                        low_line_y_12 = text_center_y(low_line_y, 14.0)
                        name_y_16 = text_center_y(name_y, 16.0)
                        top_left_x, top_right_x = (
                            x_span_at_y(l_poly_points, top_line_y)
                            if l_poly_points
                            else (frame_left, frame_right)
                        )
                        low_left_x, low_right_x = (
                            x_span_at_y(l_poly_points, low_line_y)
                            if l_poly_points
                            else (frame_left, frame_right)
                        )
                        name_left_x, name_right_x = (
                            x_span_at_y(l_poly_points, name_y)
                            if l_poly_points
                            else (frame_left, frame_right)
                        )
                        # For triangle L tiles, force text anchors to the full frame width
                        # (same x-reference style as square tiles).
                        if is_l_triangle:
                            top_left_x, top_right_x = frame_left, frame_right
                            low_left_x, low_right_x = frame_left, frame_right
                            name_left_x, name_right_x = frame_left, frame_right
                        top_pad = max(4.0, min(18.0, (top_right_x - top_left_x) * 0.03))
                        low_pad = max(4.0, min(18.0, (low_right_x - low_left_x) * 0.03))
                        is_trapezoid = rows == 5 and abs((top_right_x - top_left_x) - (low_right_x - low_left_x)) > 1.0
                        h1_extra = max(3.0, top_pad * 0.7) if is_trapezoid else 0.0
                        h1_x = top_left_x + top_pad + h1_extra
                        h4_x = top_right_x - top_pad
                        # Tile-specific right shift for top-left sequence anchor (requested):
                        # L_seed_2: about 4 characters; L_seed_1: about 9 characters.
                        extra_chars_by_tile = {"L_seed_2": 4, "L_seed_1": 11}
                        char_px = 8.4  # Approx width for 14pt Courier-family glyphs.
                        tile_name_key = tile_obj.tile_name if tile_obj is not None else ""
                        h1_shift = float(extra_chars_by_tile.get(tile_name_key, 0)) * char_px
                        if h1_shift > 0.0:
                            h1_x += h1_shift
                            # Keep room so h1 text doesn't collide with h4-side content.
                            h1_x = min(h1_x, h4_x - max(22.0, 3.0 * char_px))
                        h2_x = low_left_x + low_pad
                        h3_x = low_right_x - low_pad
                        top_mid_x = (h1_x + h4_x) / 2.0
                        low_mid_x = (low_left_x + low_right_x) / 2.0
                        name_mid_x = (name_left_x + name_right_x) / 2.0
                        ss_pad = max(4.0, min(18.0, (frame_right - frame_left) * 0.03))

                        if show_frame_guides:
                            guide_style = (
                                'fill="none" stroke="#444444" stroke-width="0.8" '
                                'stroke-opacity="0.25" stroke-dasharray="3,3"'
                            )
                            svg.append(
                                f'<rect x="{frame_left:.2f}" y="{frame_top:.2f}" '
                                f'width="{(frame_right - frame_left):.2f}" height="{frame_h:.2f}" {guide_style}/>'
                            )
                            for i in range(1, rows):
                                gy = frame_top + row_h * i
                                svg.append(
                                    f'<line x1="{frame_left:.2f}" y1="{gy:.2f}" x2="{frame_right:.2f}" y2="{gy:.2f}" '
                                    'stroke="#444444" stroke-width="0.9" stroke-opacity="0.28" stroke-dasharray="2,2"/>'
                                )

                        # Top frame text: h1 left, h4 right.
                        svg.append(
                            f'<text x="{h1_x:.2f}" y="{top_line_y_12:.2f}" text-anchor="start" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(h1_seq)}</text>'
                        )
                        svg.append(
                            f'<text x="{h4_x:.2f}" y="{top_line_y_12:.2f}" text-anchor="end" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(h4_seq)}</text>'
                        )

                        # Lower frame text: h2 left, h3 right.
                        svg.append(
                            f'<text x="{h2_x:.2f}" y="{low_line_y_12:.2f}" text-anchor="start" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(h2_seq)}</text>'
                        )
                        svg.append(
                            f'<text x="{h3_x:.2f}" y="{low_line_y_12:.2f}" text-anchor="end" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(low_right_seq)}</text>'
                        )

                        if rows == 5:
                            line2_y = frame_top + row_h * 1.5
                            line3_y = frame_top + row_h * 2.5
                            line4_y = frame_top + row_h * 3.5
                            for ly in (line2_y, line3_y, line4_y):
                                _l, r = (
                                    x_span_at_y(l_poly_points, ly)
                                    if l_poly_points
                                    else (frame_left, frame_right)
                                )
                                svg.append(
                                    f'<text x="{(r - ss_pad):.2f}" y="{text_center_y(ly, 14.0):.2f}" text-anchor="end" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">SS</text>'
                                )
                            top_bb = bb_text(c3_len)
                            if top_bb:
                                top_bb_x, _top_bb_fits = fit_mid_text_x(
                                    h1_x,
                                    h1_seq,
                                    h4_x,
                                    h4_seq,
                                    top_mid_x,
                                    top_bb,
                                    char_px=8.4,
                                )
                                svg.append(
                                    f'<text x="{top_bb_x:.2f}" y="{top_line_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(top_bb)}</text>'
                                )
                            low_bb = bb_text(c2_len)
                            if low_bb:
                                low_bb_x, _low_bb_fits = fit_mid_text_x(
                                    h2_x,
                                    h2_seq,
                                    h3_x,
                                    low_right_seq,
                                    low_mid_x,
                                    low_bb,
                                    char_px=8.4,
                                )
                                svg.append(
                                    f'<text x="{low_bb_x:.2f}" y="{low_line_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(low_bb)}</text>'
                                )
                        else:
                            line2_y = frame_top + row_h * 1.5
                            _l2, r2 = (
                                x_span_at_y(l_poly_points, line2_y)
                                if l_poly_points
                                else (frame_left, frame_right)
                            )
                            if is_l_triangle:
                                r2 = frame_right
                            svg.append(
                                f'<text x="{(r2 - ss_pad):.2f}" y="{text_center_y(line2_y, 14.0):.2f}" text-anchor="end" '
                                f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">SS</text>'
                            )
                            low_bb = bb_text(c2_len)
                            if low_bb:
                                low_bb_x, _low_bb_fits = fit_mid_text_x(
                                    h2_x,
                                    h2_seq,
                                    h3_x,
                                    low_right_seq,
                                    low_mid_x,
                                    low_bb,
                                    char_px=8.4,
                                )
                                svg.append(
                                    f'<text x="{low_bb_x:.2f}" y="{low_line_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(low_bb)}</text>'
                                )

                        svg.append(
                            f'<text x="{name_mid_x:.2f}" y="{name_y_16:.2f}" text-anchor="middle" dominant-baseline="middle" '
                            f'font-family="Arial, sans-serif" font-size="16" font-weight="bold" fill="#111111">{escape(label)}</text>'
                        )
                        continue

                    if entry.kind == "W":
                        # Normalize W display to 3 guide rows.
                        frame_left = shape_left
                        frame_right = shape_right
                        frame_cy = (shape_top + shape_bottom) / 2.0
                        frame_h = max(shape_bottom - shape_top, 36.0)
                        frame_top = frame_cy - frame_h / 2.0
                        frame_bottom = frame_cy + frame_h / 2.0
                        row_h = frame_h / 3.0
                        if show_frame_guides and frame_right > frame_left:
                            guide_style = (
                                'fill="none" stroke="#444444" stroke-width="0.8" '
                                'stroke-opacity="0.25" stroke-dasharray="3,3"'
                            )
                            svg.append(
                                f'<rect x="{frame_left:.2f}" y="{frame_top:.2f}" '
                                f'width="{(frame_right - frame_left):.2f}" height="{frame_h:.2f}" {guide_style}/>'
                            )
                            for i in range(1, 3):
                                gy = frame_top + row_h * i
                                svg.append(
                                    f'<line x1="{frame_left:.2f}" y1="{gy:.2f}" x2="{frame_right:.2f}" y2="{gy:.2f}" '
                                    'stroke="#444444" stroke-width="0.9" stroke-opacity="0.28" stroke-dasharray="2,2"/>'
                                )
                        seq_map = tile_seq_map.get(entry.tile_id, {})
                        pad_x = max(4.0, min(18.0, (frame_right - frame_left) * 0.03))
                        top_y = frame_top + row_h * 0.5
                        mid_y = frame_top + row_h * 1.5
                        low_y = frame_top + row_h * 2.5
                        marker_size = max(2.5, row_h * 0.35)
                        marker_pad_x = max(7.0, pad_x * 1.1) + marker_size * 0.6
                        marker_pad_y = max(1.5, row_h * 0.15)
                        marker_x = frame_right - marker_pad_x
                        top_marker_y = top_y + marker_pad_y
                        bottom_marker_y = low_y - marker_pad_y
                        ss_x = frame_right - pad_x
                        top_y_12 = text_center_y(top_y, 14.0)
                        mid_y_12 = text_center_y(mid_y, 14.0)
                        low_y_12 = text_center_y(low_y, 14.0)
                        name_y_16 = text_center_y(mid_y, 16.0)

                        svg.append(
                            f'<text x="{ss_x:.2f}" y="{mid_y_12:.2f}" text-anchor="end" '
                            f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">SS</text>'
                        )

                        disp_name = label
                        if entry.indicator == "circle":
                            # Block W tile: h2/h3 on bottom line, circle on top-right.
                            left_seq = seq_map.get("h2", "")
                            right_seq = seq_map.get("h3", "")
                            svg.append(
                                f'<text x="{(frame_left + pad_x):.2f}" y="{low_y_12:.2f}" text-anchor="start" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(left_seq)}</text>'
                            )
                            svg.append(
                                f'<text x="{(frame_right - pad_x):.2f}" y="{low_y_12:.2f}" text-anchor="end" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(right_seq)}</text>'
                            )
                            r = max(1.5, marker_size * 0.45)
                            svg.append(
                                f'<circle cx="{marker_x:.2f}" cy="{top_marker_y:.2f}" r="{r:.2f}" fill="#111111"/>'
                            )
                            low_bb = bb_text(c2_len)
                            if low_bb:
                                svg.append(
                                    f'<text x="{cx_s:.2f}" y="{low_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(low_bb)}</text>'
                                )
                        elif entry.indicator == "up":
                            # Lower half A: h2/h3 on bottom, triangle-up on top-right.
                            disp_name = f"{label}(A)"
                            left_seq = seq_map.get("h2", "")
                            right_seq = seq_map.get("h3", "")
                            svg.append(
                                f'<text x="{(frame_left + pad_x):.2f}" y="{low_y_12:.2f}" text-anchor="start" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(left_seq)}</text>'
                            )
                            svg.append(
                                f'<text x="{(frame_right - pad_x):.2f}" y="{low_y_12:.2f}" text-anchor="end" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(right_seq)}</text>'
                            )
                            p1 = (marker_x, top_marker_y - marker_size * 0.5)
                            p2 = (marker_x - marker_size * 0.5, top_marker_y + marker_size * 0.5)
                            p3 = (marker_x + marker_size * 0.5, top_marker_y + marker_size * 0.5)
                            svg.append(
                                f'<polygon points="{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} '
                                f'{p3[0]:.2f},{p3[1]:.2f}" fill="#111111"/>'
                            )
                            low_bb = bb_text(c2_len)
                            if low_bb:
                                svg.append(
                                    f'<text x="{cx_s:.2f}" y="{low_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(low_bb)}</text>'
                                )
                        elif entry.indicator == "down":
                            # Upper half B: h1/h4 on top, triangle-down on bottom-right.
                            disp_name = f"{label}(B)"
                            left_seq = seq_map.get("h1", "")
                            right_seq = seq_map.get("h4", "")
                            svg.append(
                                f'<text x="{(frame_left + pad_x):.2f}" y="{top_y_12:.2f}" text-anchor="start" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(left_seq)}</text>'
                            )
                            svg.append(
                                f'<text x="{(frame_right - pad_x):.2f}" y="{top_y_12:.2f}" text-anchor="end" '
                                f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                                f'fill="#1f1f1f">{escape(right_seq)}</text>'
                            )
                            p1 = (marker_x, bottom_marker_y + marker_size * 0.5)
                            p2 = (marker_x - marker_size * 0.5, bottom_marker_y - marker_size * 0.5)
                            p3 = (marker_x + marker_size * 0.5, bottom_marker_y - marker_size * 0.5)
                            svg.append(
                                f'<polygon points="{p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f} '
                                f'{p3[0]:.2f},{p3[1]:.2f}" fill="#111111"/>'
                            )
                            top_bb = bb_text(c3_len)
                            if top_bb:
                                svg.append(
                                    f'<text x="{cx_s:.2f}" y="{top_y_12:.2f}" text-anchor="middle" '
                                    f'dominant-baseline="middle" font-family="{anno_font_family}" font-size="14" font-weight="bold" '
                                    f'fill="#1f1f1f">{escape(top_bb)}</text>'
                                )

                        # Middle line center: row 2 of 3 for W tiles.
                        svg.append(
                            f'<text x="{cx_s:.2f}" y="{name_y_16:.2f}" text-anchor="middle" dominant-baseline="middle" '
                            f'font-family="Arial, sans-serif" font-size="16" font-weight="bold" fill="#111111">{escape(disp_name)}</text>'
                        )
                        continue
                    else:
                        seq_lines = l_seq_lines(entry.tile_id)
                    seq_lines = [line for line in seq_lines if line]

                    span = max(8.0, min(15.0, (h_s * 0.22) if h_s > 0.0 else 10.0))
                    name_y = cy_s
                    if len(seq_lines) == 1:
                        svg.append(
                            f'<text x="{cx_s:.2f}" y="{(cy_s - span * 0.70):.2f}" text-anchor="middle" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(seq_lines[0])}</text>'
                        )
                        name_y = cy_s + span * 0.65
                    elif len(seq_lines) >= 2:
                        svg.append(
                            f'<text x="{cx_s:.2f}" y="{(cy_s - span):.2f}" text-anchor="middle" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(seq_lines[0])}</text>'
                        )
                        svg.append(
                            f'<text x="{cx_s:.2f}" y="{(cy_s + span):.2f}" text-anchor="middle" '
                            f'dominant-baseline="middle" font-family="{seq_font_family}" font-size="14" font-weight="bold" '
                            f'fill="#1f1f1f">{escape(seq_lines[1])}</text>'
                        )
                        name_y = cy_s

                    svg.append(
                        f'<text x="{cx_s:.2f}" y="{name_y:.2f}" text-anchor="middle" dominant-baseline="middle" '
                        f'font-family="Arial, sans-serif" font-size="16" font-weight="bold" fill="#111111">{escape(label)}</text>'
                    )

        svg.append("</svg>")
        try:
            out_path.write_text("\n".join(svg), encoding="utf-8")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Export 2D SVG",
                f"Failed to write SVG:\n{exc}",
            )
            return None

        self.status.setText(f"2D SVG exported: {out_path.name}")
        if show_dialog:
            QtWidgets.QMessageBox.information(
                self,
                "Export 2D SVG",
                f"2D SVG exported:\n{out_path}",
            )
        return out_path

    def _update_maps(self) -> None:
        for widget in self._map_widgets.values():
            widget.update()

    def _refresh_selected_list(self) -> None:
        self.selected_list.clear()
        self.selected_count_label.setText(f"Selected tiles: {len(self._tile_selected)}")

        l_items: list[tuple[tuple[int, int], str]] = []
        w_items: list[tuple[tuple[int, int], str]] = []

        def label_key(lbl: str) -> tuple[int, int]:
            try:
                z_s, idx_s = lbl[1:].split("_", 1)
                return (int(z_s), int(idx_s))
            except Exception:
                return (9999, 9999)

        for tile_id in sorted(self._tile_selected):
            label = self._tile_label.get(tile_id, str(tile_id))
            disp = self._tile_display.get(tile_id)
            if disp is None:
                entry = label
            else:
                if label.startswith("W"):
                    y, x_rank, z = disp
                    entry = f"{label} (Y={y}, x={x_rank}, z={z})"
                else:
                    z, x_rank, y = disp
                    entry = f"{label} (Z={z}, x={x_rank}, y={y})"

            if label.startswith("L"):
                l_items.append((label_key(label), entry))
            elif label.startswith("W"):
                w_items.append((label_key(label), entry))
            else:
                l_items.append(((9999, 9999), entry))

        if l_items:
            self.selected_list.addItem("# XY L tiles")
            for _, entry in sorted(l_items, key=lambda t: t[0]):
                self.selected_list.addItem(entry)

        if w_items:
            if l_items:
                self.selected_list.addItem("")
            self.selected_list.addItem("# Wall / XZ tiles")
            for _, entry in sorted(w_items, key=lambda t: t[0]):
                self.selected_list.addItem(entry)


def main() -> int:
    if QtWidgets is None or QtCore is None or QtGui is None:
        print(f"Qt not available: {_qt_import_error}", file=sys.stderr)
        return 1
    if _app_import_error is not None:
        print(f"App module import failed: {_app_import_error}", file=sys.stderr)
        return 1

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
    fmt = QtGui.QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(3, 2)
    fmt.setProfile(QtGui.QSurfaceFormat.CoreProfile)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
