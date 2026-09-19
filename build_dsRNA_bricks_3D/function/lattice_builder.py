from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from .types import GlobalParams, LatticeBuildResult, TileSpec

REQUIRED_TILE_MODULES = [
    "C_Tile_L_1",
    "C_Tile_L_block_3",
    "C_Tile_L_block_4",
    "C_Tile_L_block_1",
    "C_Tile_L_seed_1",
    "C_Tile_L_seed_2",
    "C_Tile_W_seed_1",
    "C_Tile_W_block_1",
    "C_Tile_W_block_2",
    "C_Tile_W_1",
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
    if nx < 2 or ny < 2 or nz < 2:
        raise ValueError("X, Y, Z must be >= 2")

    mod_l1 = modules["C_Tile_L_1"]
    mod_block3 = modules["C_Tile_L_block_3"]
    mod_block4 = modules["C_Tile_L_block_4"]
    mod_block = modules["C_Tile_L_block_1"]
    mod_seed1 = modules["C_Tile_L_seed_1"]
    mod_seed2 = modules["C_Tile_L_seed_2"]
    mod_w_seed1 = modules["C_Tile_W_seed_1"]
    mod_w_block1 = modules["C_Tile_W_block_1"]
    mod_w_block2 = modules["C_Tile_W_block_2"]
    mod_w1 = modules["C_Tile_W_1"]

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

    for kz in range(nz):
        color = LIGHT_ORANGE if (kz % 2 == 1) else LIGHT_BLUE
        y_even = (ny % 2 == 0)

        if kz == 0:
            for y in range(0, ny, 2):
                add_tile(mod_block, "L_block_1", 0, y, kz, color)

            for k in range(0, nx - 1):
                x = 1 + 4 * k
                add_tile(mod_seed1, "L_seed_1", x, 0, kz, color)

            for k in range(0, nx):
                x = 1 + 4 * k
                for y in range(1, ny, 2):
                    add_tile(mod_seed2, "L_seed_2", x, y, kz, color)

            for k in range(0, nx - 1):
                x = 3 + 4 * k
                for y in range(2, ny, 2):
                    add_tile(mod_seed2, "L_seed_2", x, y, kz, color)

            y = ny
            if y_even:
                for k in range(0, nx - 1):
                    x = 3 + 4 * k
                    add_tile(mod_block4, "L_block_4", x, y, kz, color)
            else:
                for k in range(0, nx - 1):
                    x = 1 + 4 * k
                    add_tile(mod_block4, "L_block_4", x, y, kz, color)

        elif kz % 2 == 1:
            for k in range(0, nx):
                x = 0 + 4 * k
                y_range = range(1, ny, 2) if y_even else range(1, ny - 1, 2)
                for y in y_range:
                    add_tile(mod_l1, "L_1", x, y, kz, color)

            for k in range(0, nx):
                x = 2 + 4 * k
                for y in range(2, ny, 2):
                    add_tile(mod_l1, "L_1", x, y, kz, color)

            y = ny
            x_start = 2 if y_even else 0
            k_range = range(0, nx - 1) if y_even else range(0, nx)
            for k in k_range:
                x = x_start + 4 * k
                add_tile(mod_block3, "L_block_3", x, y, kz, color)
        else:
            for k in range(0, nx):
                x = 2 + 4 * k
                y_range = range(1, ny, 2) if y_even else range(1, ny - 1, 2)
                for y in y_range:
                    add_tile(mod_l1, "L_1", x, y, kz, color)

            for k in range(0, nx):
                x = 0 + 4 * k
                for y in range(2, ny, 2):
                    add_tile(mod_l1, "L_1", x, y, kz, color)

            y = ny
            x_start = 0 if y_even else 2
            k_range = range(0, nx) if y_even else range(0, nx - 1)
            for k in k_range:
                x = x_start + 4 * k
                add_tile(mod_block3, "L_block_3", x, y, kz, color)

    z_end_odd = nz if (nz % 2 == 1) else (nz - 2)

    for k in range(0, nx - 1):
        x = 3 + 4 * k
        for z0 in range(0, nz - 1, 2):
            add_tile(mod_w_seed1, "W_seed_1", x, 1, z0, LIGHT_GREEN)

    for k in range(0, nx):
        x = 1 + 4 * k
        for z0 in range(1, z_end_odd, 2):
            add_tile(mod_w_seed1, "W_seed_1", x, 1, z0, LIGHT_GREEN)

    for y in range(1, ny + 1, 2):
        for z0 in range(0, nz - 1, 2):
            add_tile(mod_w_block1, "W_block_1", -1, y, z0, LIGHT_GREEN)

    for y in range(2, ny + 1, 2):
        for z0 in range(1, z_end_odd, 2):
            add_tile(mod_w_block1, "W_block_1", -1, y, z0, LIGHT_RED)

    for k in range(0, nx):
        x = 1 + 4 * k
        y_range = range(2, ny + 1, 2) if (ny % 2 == 0) else range(2, ny, 2)
        for y in y_range:
            for z0 in range(0, nz - 1, 2):
                add_tile(mod_w1, "W_1", x, y, z0, LIGHT_RED)

    for k in range(0, nx - 1):
        x = 3 + 4 * k
        y_range = range(2, ny + 1, 2) if (ny % 2 == 0) else range(2, ny, 2)
        for y in y_range:
            for z0 in range(1, z_end_odd, 2):
                add_tile(mod_w1, "W_1", x, y, z0, LIGHT_RED)

    for k in range(0, nx - 1):
        x = 3 + 4 * k
        for y in range(3, ny + 1, 2):
            for z0 in range(0, nz - 1, 2):
                add_tile(mod_w1, "W_1", x, y, z0, LIGHT_GREEN)

    for k in range(0, nx):
        x = 1 + 4 * k
        for y in range(3, ny + 1, 2):
            for z0 in range(1, z_end_odd, 2):
                add_tile(mod_w1, "W_1", x, y, z0, LIGHT_GREEN)

    z_top = nz - 1
    if z_top >= 0:
        if nz % 2 == 0:
            for k in range(0, nx - 1):
                x = 1 + 4 * k
                add_tile(mod_w_block2, "W_block_2", x, 1, z_top, LIGHT_GREEN)

            for k in range(0, nx - 1):
                x = 3 + 4 * k
                for y in range(2, ny + 1, 2):
                    add_tile(mod_w_block2, "W_block_2", x, y, z_top, LIGHT_RED)

            for k in range(0, nx):
                x = 1 + 4 * k
                for y in range(3, ny + 1, 2):
                    add_tile(mod_w_block2, "W_block_2", x, y, z_top, LIGHT_GREEN)
        else:
            for k in range(0, nx - 1):
                x = 3 + 4 * k
                add_tile(mod_w_block2, "W_block_2", x, 1, z_top, LIGHT_GREEN)

            for k in range(0, nx):
                x = 1 + 4 * k
                for y in range(2, ny + 1, 2):
                    add_tile(mod_w_block2, "W_block_2", x, y, z_top, LIGHT_RED)

            for k in range(0, nx - 1):
                x = 3 + 4 * k
                for y in range(3, ny + 1, 2):
                    add_tile(mod_w_block2, "W_block_2", x, y, z_top, LIGHT_GREEN)

    return LatticeBuildResult(tiles=tiles, centers=centers)


def relabel_tiles(tiles: list[TileSpec]) -> tuple[dict[int, str], dict[int, tuple[int, int, int]]]:
    labels: dict[int, str] = {}
    display: dict[int, tuple[int, int, int]] = {}

    groups_l: dict[int, list[tuple[int, int, int]]] = {}
    groups_w: dict[int, list[tuple[int, int, int]]] = {}
    groups_t: dict[int, list[tuple[int, int, int]]] = {}

    for tile in tiles:
        x, y, z = tile.lattice_pos
        tname = tile.tile_name
        if tname.startswith("L"):
            groups_l.setdefault(z, []).append((y, x, tile.tile_id))
        elif tname.startswith("W"):
            groups_w.setdefault(y, []).append((z, x, tile.tile_id))
        else:
            groups_t.setdefault(z, []).append((y, x, tile.tile_id))

    # L tiles: keep existing behavior (group by z, index y then x).
    for z, items in groups_l.items():
        row_rank: dict[int, int] = {}
        rows: dict[int, list[tuple[int, int]]] = {}
        for y, x, tile_id in items:
            rows.setdefault(y, []).append((x, tile_id))

        for y, row_items in rows.items():
            row_items.sort(key=lambda t: t[0])
            for idx, (_x, tile_id) in enumerate(row_items):
                row_rank[tile_id] = idx

        items_sorted = sorted(items, key=lambda t: (t[0], t[1]))  # y, x
        for idx, (y, _x, tile_id) in enumerate(items_sorted):
            labels[tile_id] = f"L{z}_{idx}"
            display[tile_id] = (z, row_rank.get(tile_id, 0), y)

    # W tiles: new behavior (group by y, index left->right then low->high i.e. x, z).
    for y, items in groups_w.items():
        line_rank: dict[int, int] = {}
        lines: dict[int, list[tuple[int, int]]] = {}
        for z, x, tile_id in items:
            lines.setdefault(z, []).append((x, tile_id))

        for z, line_items in lines.items():
            line_items.sort(key=lambda t: t[0])  # x
            for idx, (_x, tile_id) in enumerate(line_items):
                line_rank[tile_id] = idx

        # Order by z-layer first, then left->right within each layer.
        items_sorted = sorted(items, key=lambda t: (t[0], t[1]))  # z, x
        for idx, (z, _x, tile_id) in enumerate(items_sorted):
            labels[tile_id] = f"W{y}_{idx}"
            display[tile_id] = (y, line_rank.get(tile_id, 0), z)

    # Fallback for any other tile category.
    for z, items in groups_t.items():
        row_rank: dict[int, int] = {}
        rows: dict[int, list[tuple[int, int]]] = {}
        for y, x, tile_id in items:
            rows.setdefault(y, []).append((x, tile_id))
        for yv, row_items in rows.items():
            row_items.sort(key=lambda t: t[0])
            for idx, (_x, tile_id) in enumerate(row_items):
                row_rank[tile_id] = idx
        items_sorted = sorted(items, key=lambda t: (t[0], t[1]))
        for idx, (yv, _x, tile_id) in enumerate(items_sorted):
            labels[tile_id] = f"T{z}_{idx}"
            display[tile_id] = (z, row_rank.get(tile_id, 0), yv)

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
