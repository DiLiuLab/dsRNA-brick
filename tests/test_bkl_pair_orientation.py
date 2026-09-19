"""Check that KL pool columns retain their bulge/loop roles in both builders."""

import importlib
import random
import sys
import types
import unittest
from unittest.mock import patch


class BklPairOrientationTests(unittest.TestCase):
    def _builder(self, dimension):
        package = f"build_dsRNA_bricks_{dimension}.function"
        lattice = importlib.import_module(f"{package}.lattice_builder")
        tile_type = importlib.import_module(f"{package}.types").TileSpec
        return lattice, tile_type

    def _tile(self, tile_type, tile_id, name, hemisphere_count):
        return tile_type(
            tile_id=tile_id,
            tile_name=name,
            lattice_pos=(0, 0, 0),
            color="",
            mesh=None,
            hemi_positions=[(0.0, 0.0, 0.0)] * hemisphere_count,
            center=(0.0, 0.0, 0.0),
        )

    def test_both_builders_keep_first_column_on_bulge(self):
        for dimension in ("2D", "3D"):
            with self.subTest(dimension=dimension):
                lattice, tile_type = self._builder(dimension)
                tiles = {
                    0: self._tile(tile_type, 0, "L_1", 4),
                    1: self._tile(tile_type, 1, "L_1", 4),
                    2: self._tile(tile_type, 2, "L_block_3", 3),
                }
                # Include both endpoint orders and both Type I/Type II layouts.
                refs = [
                    ((0, 0), (1, 2)),
                    ((0, 3), (1, 1)),
                    ((2, 1), (1, 0)),
                    ((0, 2), (2, 0)),
                ]
                pool = [(f"B{i}", f"L{i}") for i in range(8)]
                chosen = random.Random(42).sample(pool, len(refs))
                assigned = lattice.assign_kl_pool_pairs(refs, pool, tiles)
                self.assertEqual(assigned, lattice.assign_kl_pool_pairs(refs, pool, tiles))
                for (a_ref, b_ref), (bulge_seq, loop_seq) in zip(refs, chosen):
                    a_role = lattice.kl_hemisphere_role(tiles[a_ref[0]], a_ref[1])
                    bulge_ref, loop_ref = (a_ref, b_ref) if a_role == "bulge" else (b_ref, a_ref)
                    self.assertEqual(assigned[bulge_ref], bulge_seq)
                    self.assertEqual(assigned[loop_ref], loop_seq)

    def test_invalid_role_pairs_fail_instead_of_silently_swapping(self):
        for dimension in ("2D", "3D"):
            with self.subTest(dimension=dimension):
                lattice, tile_type = self._builder(dimension)
                tiles = {
                    0: self._tile(tile_type, 0, "L_1", 4),
                    1: self._tile(tile_type, 1, "L_block_3", 3),
                }
                with self.assertRaisesRegex(ValueError, "not a bulge to a loop"):
                    lattice.assign_kl_pool_pairs([((0, 0), (1, 0))], [("B", "L")], tiles)
                with self.assertRaisesRegex(ValueError, "not a bulge to a loop"):
                    lattice.assign_kl_pool_pairs([((0, 2), (1, 2))], [("B", "L")], tiles)

    def test_example_lattices_only_pair_bulges_with_loops(self):
        # PyVista is only needed to render tile meshes; use the real geometry
        # specifications without rendering so this check runs headlessly.
        for dimension, dimensions, units, expected_pairs in (
            ("2D", (3, 5, 1), (2.0, 2.5, 2.5), 21),
            ("3D", (3, 5, 4), (1.5, 2.5, 2.5), 193),
        ):
            with self.subTest(dimension=dimension):
                package = f"build_dsRNA_bricks_{dimension}.function"
                lattice, _ = self._builder(dimension)
                module_name = f"{package}.c_tiles"
                with patch.dict(sys.modules, {"pyvista": types.ModuleType("pyvista")}):
                    specs = importlib.import_module(module_name).SPECS
                sys.modules.pop(module_name, None)
                params = types.SimpleNamespace(
                    x_unit=units[0], y_unit=units[1], z_unit=units[2]
                )

                class GeometryOnlyModule:
                    def __init__(self, spec):
                        self.spec = spec

                    def make_c_tile(self, start_pos, color):
                        del color
                        points = [
                            tuple(
                                start_pos[i] + hemi.center[i] * units[i]
                                for i in range(3)
                            )
                            for hemi in self.spec.hemispheres
                        ]
                        return None, points

                modules = {name: GeometryOnlyModule(spec) for name, spec in specs.items()}
                tiles = lattice.build_lattice(*dimensions, modules, params).tiles
                tile_by_id = {tile.tile_id: tile for tile in tiles}
                lookup = lattice.analyze_hemisphere_pairing(tiles)["pair_lookup"]
                refs = sorted((a, b) for a, b in lookup.items() if a < b)
                self.assertEqual(len(refs), expected_pairs)
                pool = [(f"B{i}", f"L{i}") for i in range(len(refs))]
                assigned = lattice.assign_kl_pool_pairs(refs, pool, tile_by_id)
                self.assertEqual(len(assigned), 2 * expected_pairs)
                for a_ref, b_ref in refs:
                    roles = {
                        lattice.kl_hemisphere_role(tile_by_id[a_ref[0]], a_ref[1]),
                        lattice.kl_hemisphere_role(tile_by_id[b_ref[0]], b_ref[1]),
                    }
                    self.assertEqual(roles, {"bulge", "loop"})


if __name__ == "__main__":
    unittest.main()
