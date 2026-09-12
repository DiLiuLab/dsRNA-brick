# dsRNA-brick

This repository provides an end-to-end workflow for dsRNA-brick design:

1. Build an orthogonal KL sequence pool.
2. Build/select lattice structures in 2D or 3D GUI.
3. Generate tile sequences for downstream design workflows.

## Repository Modules

- `Orthogonal_sequence_selection/`
  - KL candidate generation, conflict-graph construction, and independent-set selection.
  - One-command entry script:
    - `run_orthogonal_selection.py`
  - Internals are in `Orthogonal_sequence_selection/functions/`.

- `build_dsRNA_bricks_2D/`
  - 2D lattice GUI (`X`, `Y`) with synchronized model/XY map tile selection.
  - Integrated sequence-generation pipeline.

- `build_dsRNA_bricks_3D/`
  - 3D lattice GUI (`X`, `Y`, `Z`) with synchronized 3D/layered-map tile selection.
  - Integrated sequence-generation pipeline.

## Quick Start

### 1. Download the code

Option A (Git):

```bash
git clone https://github.com/DiLiuLab/dsRNA-brick.git dsRNA-brick
cd dsRNA-brick
```

Option B (ZIP):

1. Download ZIP from GitHub.
2. Unzip it.
3. Open terminal in the unzipped `dsRNA-brick` folder.

### 2. Set up Python environment

```bash
conda create -n dsrna python=3.12 -y
conda activate dsrna
pip install "pyside6==6.9.*" numpy matplotlib pyvista pyvistaqt vtk
```

Install/configure NUPACK separately using official documentation:

- [https://docs.nupack.org/](https://docs.nupack.org/)

Notes:

- NUPACK is required for orthogonality energy plotting in orthogonal-selection step 4 and sequence design in 2D/3D structure.

### 3. Run orthogonal sequence selection

```bash
cd Orthogonal_sequence_selection
python run_orthogonal_selection.py -N 9 -R 1000
```

Main outputs:

- `Orthogonal_RNA_Pool_9nt/RNA_Pool_9nt.txt`
- `Orthogonal_RNA_Pool_9nt/FilteredPool_9nt.txt`
- `Orthogonal_RNA_Pool_9nt/ConflictGraph_9nt.txt`
- `Orthogonal_RNA_Pool_9nt/SelectedPool_from_graph.txt`
- `Orthogonal_RNA_Pool_9nt/Orthogonal_RNA_Pool_9nt.txt`
- `Orthogonal_RNA_Pool_9nt/orthogonality_9nt_RNA_Pool.png` (requires NUPACK)

### 4. Run the 2D GUI

```bash
cd ../build_dsRNA_bricks_2D
python build_dsRNA_Bricks_2D.py
```

### 5. Run the 3D GUI

```bash
cd ../build_dsRNA_bricks_3D
python build_dsRNA_Bricks_3D.py
```


## Module Documentation

- Orthogonal selection: [`Orthogonal_sequence_selection/README.md`](Orthogonal_sequence_selection/README.md)
- 2D GUI: [`build_dsRNA_bricks_2D/README.md`](build_dsRNA_bricks_2D/README.md)
- 3D GUI: [`build_dsRNA_bricks_3D/README.md`](build_dsRNA_bricks_3D/README.md)

## Repository Structure

```text
dsRNA-brick/
├── Orthogonal_sequence_selection/
├── build_dsRNA_bricks_2D/
├── build_dsRNA_bricks_3D/
├── CITATION.cff
├── LICENSE
└── README.md
```

## Citation

If you use `dsRNA-brick` in your research, please cite:

> Chen, L., Li, Z., Yan, J., et al. (2026). Programmable Self-Assembly of RNA Nanostructures with >100 Unique Components. *bioRxiv*. https://doi.org/10.64898/2026.09.02.748990

Machine-readable citation metadata, including the complete author list, is available in [`CITATION.cff`](CITATION.cff).

## License

MIT License. See [`LICENSE`](LICENSE).
