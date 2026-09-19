from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from .types import GlobalParams, LatticeBuildResult, TileSpec

REQUIRED_TILE_MODULES = [
    "C_Tile_L_1",
    "C_Tile_L_block_3",
    "C_Tile_L_block_1",
    "C_Tile_L_seed_2",
]

LIGHT_BLUE = "#9ecae1"
LIGHT_ORANGE = "#f6c08b"
LIGHT_GREEN = "#a6dba0"
LIGHT_RED = "#f4a6a6"

TYPE_II_TILE_NAMES = {"L_block_3", "L_block_4", "W_block_2"}
HemiRef = tuple[int, int]


def kl_hemisphere_role(tile: TileSpec, hemi_idx: int) -> str:
    """Identify the physical bKL role of a tile's hemisphere endpoint."""
    if tile.tile_name in TYPE_II_TILE_NAMES:
        if len(tile.hemi_positions) != 3:
            raise ValueError(f"Unexpected KL endpoint layout for tile {tile.tile_name!r}.")
        # Type II: h2 is the loop, h3 the bulge, and h4 is a boundary cap.
        roles = ("loop", "bulge", "cap")
    elif len(tile.hemi_positions) == 4:
        # Type I: h1/h2 are stem loops; h3/h4 are bulge regions.
        roles = ("loop", "loop", "bulge", "bulge")
    else:
        raise ValueError(f"Unknown KL endpoint layout for tile {tile.tile_name!r}.")
    if not 0 <= hemi_idx < len(roles):
        raise ValueError(f"Invalid hemisphere index {hemi_idx} for tile {tile.tile_name!r}.")
    return roles[hemi_idx]


def assign_kl_pool_pairs(
    pair_refs: list[tuple[HemiRef, HemiRef]],
    pool_pairs: list[tuple[str, str]],
    tile_by_id: dict[int, TileSpec],
    *,
    seed: int = 42,
) -> dict[HemiRef, str]:
    """Sample KL pairs, keeping pool column 1 on bulges and column 2 on loops."""
    if len(pool_pairs) < len(pair_refs):
        raise ValueError("KL pool contains fewer pairs than the lattice requires.")

    assignments: dict[HemiRef, str] = {}
    for (a_ref, b_ref), (bulge_seq, loop_seq) in zip(
        pair_refs, random.Random(seed).sample(pool_pairs, len(pair_refs))
    ):
        try:
            a_role = kl_hemisphere_role(tile_by_id[a_ref[0]], a_ref[1])
            b_role = kl_hemisphere_role(tile_by_id[b_ref[0]], b_ref[1])
        except KeyError as exc:
            raise ValueError(f"Unknown tile ID {exc.args[0]} in KL pair.") from None
        if {a_role, b_role} != {"bulge", "loop"}:
            raise ValueError(
                f"KL pair {a_ref}, {b_ref} joins {a_role} to {b_role}, "
                "not a bulge to a loop."
            )
        bulge_ref, loop_ref = (a_ref, b_ref) if a_role == "bulge" else (b_ref, a_ref)
        if bulge_ref in assignments or loop_ref in assignments:
            raise ValueError(f"KL pair {a_ref}, {b_ref} reuses an assigned endpoint.")
        assignments[bulge_ref] = bulge_seq
        assignments[loop_ref] = loop_seq
    return assignments


def missing_required_modules(modules: dict[str, Any]) -> list[str]:
    return [name for name in REQUIRED_TILE_MODULES if modules.get(name) is None]


def build_lattice(
    nx: int,
    ny: int,
    nz: int,
    modules: dict[str, Any],
    params: GlobalParams,
) -> LatticeBuildResult:
    if nx < 2 or ny < 2 or nz < 1:
        raise ValueError("X, Y must be >= 2 (Z fixed internally).")

    mod_l1 = modules["C_Tile_L_1"]
    mod_block3 = modules["C_Tile_L_block_3"]
    mod_block = modules["C_Tile_L_block_1"]
    mod_seed2 = modules["C_Tile_L_seed_2"]

    tiles: list[TileSpec] = []
    centers: list[tuple[float, float, float]] = []
    tile_id = 0

    def add_tile(mod: Any, tile_name: str, x: int, y: int, z: int, color: str) -> None:
        nonlocal tile_id
        offset = (x * params.x_unit, y * params.y_unit, z * params.z_unit)
        mesh, hemi_positions = mod.make_c_tile(start_pos=offset, color=color)
        tile = TileSpec(
            tile_id=tile_id,
            tile_name=tile_name,
            lattice_pos=(x, y, z),
            color=color,
            mesh=mesh,
            hemi_positions=list(hemi_positions),
            center=offset,
        )
        tiles.append(tile)
        centers.append(offset)
        tile_id += 1

    def row_color(y: int) -> str:
        rem = y % 4
        if rem == 0:
            return LIGHT_ORANGE
        if rem == 1:
            return LIGHT_BLUE
        if rem == 2:
            return LIGHT_RED
        return LIGHT_GREEN

    # 2D lattice rules (single Z plane, z=0), user-defined:
    # 1) L_block_1: (-1,0), (-1,2), ... y < ny-1
    # 2) L_seed_2:  (0,0), (2,0), ... (2*nx-2,0)
    # 3) L_1:
    #    - (2k, y), k=0..nx-1, y odd up to ny-2
    #    - (1+2k, y), k=0..nx-2, y even up to ny-2
    # 4) L_block_3 at y=ny-1:
    #    - ny odd:  x=1+2k, k=0..nx-2
    #    - ny even: x=0+2k, k=0..nx-2
    z0 = 0

    for y in range(0, ny - 1, 2):
        add_tile(mod_block, "L_block_1", -1, y, z0, row_color(y))

    for k in range(0, nx - 1):
        x = 2 * k
        add_tile(mod_seed2, "L_seed_2", x, 0, z0, row_color(0))

    y_last = ny - 2

    for k in range(0, nx):
        x = 2 * k
        for y in range(1, y_last + 1, 2):
            add_tile(mod_l1, "L_1", x, y, z0, row_color(y))

    for k in range(0, nx - 1):
        x = 1 + 2 * k
        for y in range(2, y_last + 1, 2):
            add_tile(mod_l1, "L_1", x, y, z0, row_color(y))

    y_top = ny - 1
    if ny % 2 == 1:
        for k in range(0, nx - 1):
            x = 1 + 2 * k
            add_tile(mod_block3, "L_block_3", x, y_top, z0, row_color(y_top))
    else:
        for k in range(0, nx - 1):
            x = 0 + 2 * k
            add_tile(mod_block3, "L_block_3", x, y_top, z0, row_color(y_top))

    return LatticeBuildResult(tiles=tiles, centers=centers)


def relabel_tiles(tiles: list[TileSpec]) -> tuple[dict[int, str], dict[int, tuple[int, int, int]]]:
    labels: dict[int, str] = {}
    display: dict[int, tuple[int, int, int]] = {}

    def sort_key(tile: TileSpec) -> tuple[int, int, int, int]:
        x, y, z = tile.lattice_pos
        # Keep non-negative x before boundary x=-1 so interior starts at Tile0.
        x_group = 0 if x >= 0 else 1
        return (y, x_group, x, z, tile.tile_id)

    ordered = sorted(tiles, key=sort_key)
    for idx, tile in enumerate(ordered):
        x, y, z = tile.lattice_pos
        labels[tile.tile_id] = f"Tile{idx}"
        display[tile.tile_id] = (x, y, z)

    return labels, display


def analyze_hemisphere_pairing(
    tiles: list[TileSpec],
    *,
    precision: int = 6,
) -> dict[str, Any]:
    """
    Group hemisphere endpoints by spatial position and derive KL pairing info.

    Returns:
    - pair_lookup[(tile_id, hemi_idx)] -> (tile_id, hemi_idx) for paired endpoints
    - block_refs: set of unpaired endpoints
    - pair_count: number of endpoint pairs in lattice
    - block_count: number of unpaired endpoints
    - tile_pair_count[tile_id]: paired endpoints per tile
    - tile_block_count[tile_id]: unpaired endpoints per tile
    - tile_links[tile_id]: set of partner tile_ids
    - issues: non-fatal geometry grouping warnings
    """

    def key_for(pos: tuple[float, float, float]) -> tuple[float, float, float]:
        return (round(pos[0], precision), round(pos[1], precision), round(pos[2], precision))

    groups: dict[tuple[float, float, float], list[tuple[int, int]]] = {}
    for tile in tiles:
        for hemi_idx, pos in enumerate(tile.hemi_positions):
            groups.setdefault(key_for(pos), []).append((tile.tile_id, hemi_idx))

    pair_lookup: dict[tuple[int, int], tuple[int, int]] = {}
    block_refs: set[tuple[int, int]] = set()
    tile_pair_count: dict[int, int] = defaultdict(int)
    tile_block_count: dict[int, int] = defaultdict(int)
    tile_links: dict[int, set[int]] = defaultdict(set)
    issues: list[str] = []
    pair_count = 0

    def register_pair(a: tuple[int, int], b: tuple[int, int]) -> None:
        nonlocal pair_count
        pair_lookup[a] = b
        pair_lookup[b] = a
        tile_pair_count[a[0]] += 1
        tile_pair_count[b[0]] += 1
        if a[0] != b[0]:
            tile_links[a[0]].add(b[0])
            tile_links[b[0]].add(a[0])
        pair_count += 1

    for pos_key, refs in groups.items():
        if len(refs) == 1:
            ref = refs[0]
            block_refs.add(ref)
            tile_block_count[ref[0]] += 1
            continue

        if len(refs) == 2:
            register_pair(refs[0], refs[1])
            continue

        refs_sorted = sorted(refs, key=lambda t: (t[0], t[1]))
        issues.append(
            f"Position {pos_key} has {len(refs_sorted)} hemisphere endpoints; "
            "paired sequentially."
        )
        while len(refs_sorted) >= 2:
            a = refs_sorted.pop(0)
            b = refs_sorted.pop(0)
            register_pair(a, b)
        if refs_sorted:
            ref = refs_sorted.pop(0)
            block_refs.add(ref)
            tile_block_count[ref[0]] += 1

    for tile in tiles:
        tile_pair_count.setdefault(tile.tile_id, 0)
        tile_block_count.setdefault(tile.tile_id, 0)
        tile_links.setdefault(tile.tile_id, set())

    return {
        "pair_lookup": pair_lookup,
        "block_refs": block_refs,
        "pair_count": pair_count,
        "block_count": len(block_refs),
        "tile_pair_count": dict(tile_pair_count),
        "tile_block_count": dict(tile_block_count),
        "tile_links": {k: set(v) for k, v in tile_links.items()},
        "issues": issues,
    }
