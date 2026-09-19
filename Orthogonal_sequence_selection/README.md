# Orthogonal (b)KL Sequence Selection

## Big Picture Pipeline

For `N` (default `9`), the workflow has 4 steps:

1. Generate candidate RNA pool
   - Output: `RNA_Pool_Nnt.txt`

2. Filter candidates and build conflict graph
   - Outputs: `FilteredPool_Nnt.txt`, `ConflictGraph_Nnt.txt`

3. Select a large non-conflicting set (independent set)
   - Output: `SelectedPool_from_graph.txt`

4. Generate full complementary pairs and orthogonality figure
   - Outputs: `Orthogonal_RNA_Pool_Nnt.txt`, `orthogonality_Nnt_RNA_Pool.png`

All files are written into a new folder:

- `Orthogonal_RNA_Pool_Nnt`

(Here `N` is replaced by your `--num-nt` value, e.g. `9`.)

---

## Requirements

- Python 3.9+.
- GUI mode: `PySide6` (`pip install PySide6`).
- Command-line steps 1–3: standard Python library only.
- Step 4 figure (`orthogonality_Nnt_RNA_Pool.png`): requires `nupack` (and `matplotlib`, `numpy`).
- If `nupack` is not installed, the pipeline still completes and still writes:
  - `Orthogonal_RNA_Pool_Nnt.txt`
  - all step 1–3 files
  - plus a warning: `No NUPACK` (figure is skipped).

---

## How To Run

With no arguments, the PySide6 GUI opens. Enter the sequence length, exact G/C
base count, number of selection rounds, guide RNA sequences, and optional final
output filename, then click **Run selection**. The window displays live pipeline output and completion
status. It runs the same four steps as command-line mode and saves results in
`Orthogonal_RNA_Pool_<N>nt/` under the current working directory. If that folder
already exists, the GUI asks before reusing it. Click a light-blue **?** button
beside any parameter for an explanation and example.

```bash
python run_orthogonal_selection.py
```

Use `--gui` to open the GUI explicitly. Options supplied with `--gui` prefill
its fields, for example `python run_orthogonal_selection.py --gui -N 9 -R 2000`.
Any normal pipeline option without `--gui` runs non-interactively. Use `--cli`
for a non-interactive run with all defaults. The GUI is not needed for CLI mode.

Use `--help` (or `-h`) for the standard argument list, or `-U` for the longer
built-in usage instructions; neither opens the GUI.

Example output folder:

- `Orthogonal_RNA_Pool_9nt/`

Example files inside:

- `RNA_Pool_9nt.txt`
- `FilteredPool_9nt.txt`
- `ConflictGraph_9nt.txt`
- `SelectedPool_from_graph.txt`
- `Orthogonal_RNA_Pool_9nt.txt`
- `orthogonality_9nt_RNA_Pool.png`

---

## Supported Options

- `-N`, `--num-nt`
  - Meaning: sequence length `N`.
  - Default: `9`.

- `-C`, `--gc-count`
  - Meaning: exact total number of G/C bases in each generated sequence (not separate G and C quotas).
  - Default: `4`; valid range: `2` to `N-2`.

- `-R`, `--rounds`
  - Meaning: number of randomized attempts in step 3.
  - Default: `1000`.

- `-G`, `--guide`
  - Meaning: guide sequence used in filtering (step 2).
  - Default: `CACGAAGUCAAUAC`.
  - Multiple guides are allowed by repeating `-G`.

- `-O`, `--output`
  - Meaning: filename of step-4 text output.
  - Default: `Orthogonal_RNA_Pool_Nnt.txt`.

- `-U`, `--User`
  - Meaning: show built-in usage instructions.

---

## Detailed Step Introduction

## Step 1 – `generate_pool_nnt.py`

**Goal:** enumerate “nice” N‑nt KL candidates (for us N = 9) with controlled GC content, no obvious hairpins, and reasonable end patterns.

### How to run it (9‑nt example)

From `Orthogonal_sequence_selection/`:


```
python functions/generate_pool_nnt.py 9
```
- **Positional argument**: `N` (here `9`)
- **Optional**: `-C` / `--gc-count` (default `4`; e.g. `-C 5` for five G/C positions)
- **Optional**: `--output <filename>`

If you don’t give `--output`, it will write to: `RNA_Pool_9nt.txt` (one sequence per line, all uppercase RNA).

Example (first lines of `Orthogonal_RNA_Pool_9nt/RNA_Pool_9nt.txt`):

```text
CGGUAAGAA
GCGUAAGAA
CCGUAAGAA
GGCUAAGAA
CGCUAAGAA
GCCUAAGAA
```

### What the G/C count means

- It works at two levels:
1. **S/W pattern** level: "strong" vs "weak"
- **S = strong** = G or C
- **W = weak**  = A or U

2. **Base assignment** level: choose actual A/G/U/C consistent with that S/W pattern.

By default, for N = 9 the script enforces **exactly 4 S and 5 W**, so **every 9‑mer has 4 G/C and 5 A/U**. With `-C 5`, it instead uses **5 S and 4 W**. At least two of each class are required because every candidate must contain A, U, G, and C.

#### S/W pattern generation (function `gen_pattern_sw`)

With the default four G/C positions, the original C++ pattern-generation logic and output order are preserved. For a custom count, the script enumerates S/W placements and rejects patterns containing four consecutive S or four consecutive W; the later sequence-level filters are unchanged.

For each default 9‑nt pattern, the original logic:

- Picks positions of the 4 S’s (indices Sa, Sb, Sc, Sd) and fills the rest with W.
- Rejects patterns that:
- have **4 consecutive S** (avoids long GC runs),
- have a **long run of W at the 5′ end** (avoids very A/U‑rich 5′ segments, following the original C++ logic).

Result: a list of strings like `"swwswwsww"` that tell you where G/C vs A/U are allowed.

#### Assigning A/G/U/C (function `assign_seq_for_pattern`)

For each S/W pattern, it enumerates all `2^N` assignments:

- At each W position: choose **A or U**
- At each S position: choose **G or C**

For each resulting sequence `s` (length 9), it applies filters:

1. **All four nucleotides must appear at least once**
- `s` must contain **A, G, U, and C** somewhere.

2. **Hairpin exclusion (for N ≥ 9, so yes for 9‑mers)**
- It looks at the would‑be stem formed by the outer 3 pairs:
- Pairs `s[0]–s[-1]`, `s[1]–s[-2]`, `s[2]–s[-3]`.

- Two scores:
- `score` using normal base pairs (AU, UA, GC, CG, GU, UG),
- `score_comp` using a slightly different “complement” rule (allows AC/CA).

- If **all three** outer positions look pairable in either sense (`score ≥ 3` or `score_comp ≥ 3`), the sequence is **discarded** – it’s too hairpin‑like.

3. **No internal “UUU” or mirrored “AAA”**
- For positions `i = 2 ... N-3` (internal):
- Reject if there is `U U U` at `s[i:i+3]`.
- Reject if there is `A A A` at the **mirrored** positions at the 5′ side.

- So we avoid long **internal U‑tracts and A‑tracts**, which are structurally problematic.

Sequences passing these tests are collected into a pool.

#### Final refinement filters (function `refine_seq`)

After pooling all candidates from all patterns, `refine_seq` applies four more rules:

1. `if6_kmry` **– avoid 6‑long degenerate runs**
- K = {G, U}
- M = {A, C}
- R = {A, G}
- Y = {C, U}
- It tracks the longest consecutive run for each group (K, M, R, Y).
   If **any group has length ≥ 6**, the sequence is **rejected**. → Roughly: no “6 bases in a row that all behave like purines, pyrimidines, etc.”

2. `if_ends_ww` **– both ends weak? reject**
- If both 5′ and 3′ ends are A/U (in any combination A/U vs A/U) the sequence is rejected.
- Ensures **at least one end has a G or C**, which stabilises the designed KL and reduces problematic 3′/5′ fluff.

3. `if_ends_3w` **– 3 weak bases at either end**
- If positions 0–2 or positions N-3–N-1 are all A/U, reject.

4. `if_ends_pair_u` **– more detailed end hairpin checks**
- For N ≥ 9, it looks for patterns like:
- 5′ A at the start or 3′ U at the end,
- short A‑rich segments at 5′ that could strongly pair with 3′,
- 3′ terminal U or UU that could form a little end‑stem with the 5′ side.

- If these patterns indicate likely terminal pairing, the sequence is rejected.



---

## Step 2 – `build_rna_conflict_graphV2.py`

**Goal:** from the raw pool, throw away self‑complementary and guide‑complementary sequences, then build a **graph of pairwise conflicts** based on strong complementarity.

### How to run it (9‑nt example)

Basic usage with defaults:


```
python build_rna_conflict_graphV2.py --num-nt 9
```
- `--num-nt 9` tells it we are working with 9‑mers.
- If you don’t give `--input`, it assumes: (the output of Step 1).
- Default guide(s): `DEFAULT_GUIDES = ["CACGAAGUCAAUAC"]`
   (this is the 15‑nt handle used in the bricks scripts). You can override:


```
python build_rna_conflict_graphV2.py \
--num-nt 9 \
--input RNA_Pool_9nt.txt \
--guide CACGAAGUCAAUAC --guide GGGAAAUUU \
```
The run time of the code could be up to 2 hours. 

With defaults you get:

- `FilteredPool_9nt.txt`
- `ConflictGraph_9nt.txt`

Example (first lines of `Orthogonal_RNA_Pool_9nt/FilteredPool_9nt.txt`):

```text
CGGUAAGAA
GCGUAAGAA
CCGUAAGAA
GGCUAAGAA
CGCUAAGAA
GCCUAAGAA
```

Example (first lines of `Orthogonal_RNA_Pool_9nt/ConflictGraph_9nt.txt`):

```text
0	1
0	2
0	3
0	4
0	7
0	8
```

### Step 2a – read and pre‑filter

1. **Read all sequences** (must have length `num_nt`).
2. **Remove palindromes / self‑complementary sequences**
- A sequence counts as “palindromic” if it is complementary to itself under the same rules used for pairwise complementarity (including GU wobble).

3. **Remove sequences that conflict with guide sequences**For each guide:
- Generate all contiguous 9‑mers from the guide.
- For each pool sequence, check if it is “too complementary” to **any** of those 9‑mers (with all reverse‑complement orientations).
- If yes → discard the pool sequence.

This ensures **no KL candidate binds strongly to the constant handle (or any other guide you specify).**

### Step 2b – complementarity rules and the conflict graph

Now you have a filtered list of sequences `seqs`. The script builds an undirected graph:

- **One node per sequence.**
- An **edge (i, j)** means sequences **i** and **j** are “too complementary” under the custom rules.

Under the hood:

- Base pairs allowed:
- Watson–Crick: **A‑U, U‑A, G‑C, C‑G**
- GU wobble: **G‑U, U‑G**

- For each pair `(s1, s2)` it checks **all four combinations**:
- `s1` vs `s2`
- `s1` vs reverse‑complement(s2)
- reverse‑complement(s1) vs `s2`
- reverse‑complement(s1) vs reverse‑complement(s2)

The **complementarity criteria** are exactly summarized in the header of the script:

Two sequences (or their RCs) are considered a **conflicting pair** if **any** of these holds:

1. **Global pairing**
- There exists an alignment with:
- at least **N–1 paired positions**, and
- **> 2 GC pairs**.

2. **Very long consecutive pairing**
- Alignment has a **longest consecutive run ≥ N–1**, and
- **> 1 GC pair** in that alignment.

3. **Medium consecutive pairing**
- Longest consecutive run ≥ **N–2**, and
- **> 2 GC pairs**.

4. **Shorter but GC‑rich**
- Longest consecutive run ≥ **N–3**, and
- **≥ 4 GC pairs**.

5. **Bulged pairing (N ≥ 9)**
- There exists a **single‑bulge alignment** of length **N–1** between the two sequences (one base skipped on one strand) with **≥ 3 GC pairs**.

For **N = 9** these thresholds are:

- N–1 = **8**, N–2 = **7**, N–3 = **6**.
- So two 9‑mers conflict if e.g.:
- They can form ~8 bp with several GC pairs, **or**
- They have a contiguous 8‑bp run with >1 GC, **or**
- They have a contiguous 7‑bp run with >2 GC, **or**
- They have a contiguous 6‑bp run with ≥4 GC, **or**
- They can form an **8‑bp single‑bulged** alignment with ≥3 GC.

This is more nuanced than just “no 5‑bp perfect complement”—it balances **length of interaction** and **GC richness**, which controls the expected stability.

**Output of Step 2 (for N=9):**

- **Filtered sequences** (post palindrome + guide filter)
   → `FilteredPool_9nt.txt`
- **Conflict graph edge list**
   → `ConflictGraph_9nt.txt`(each line: `i<TAB>j`, with `0 ≤ i < j`)



---

## Step 3 – `select_from_conflict_graph.py`

**Goal:** choose a large subset of sequences that have **no edges between them** – a big independent set in the conflict graph.

### How to run it (9‑nt example)

If you used the defaults in Step 2:


```
python select_from_conflict_graph.py \
--seq-file   FilteredPool_9nt.txt \
--graph-file ConflictGraph_9nt.txt \
--rounds 1000
```
It will write: `SelectedPool_from_graph.txt` 

Each line:


```
index<TAB>sequence
```
(the index matches the line number in `FilteredPool_9nt.txt`).

Example (first lines of `Orthogonal_RNA_Pool_9nt/SelectedPool_from_graph.txt`):

```text
6845	CAUGAUUGC
4186	CUCUAGUUC
4552	CUACUGUUC
2298	GUUACCUCA
6032	UACGAUCUC
2695	GCUACAUAG
```

Key arguments:

- `--seq-file` : filtered sequences from Step 2
- `--graph-file` : edge list from Step 2
- `--rounds` : number of randomized greedy attempts (default 1000)
- `--seed` : random seed (optional but good for reproducibility)
- `--output` : base name for output file (default `SelectedPool_from_graph.txt` → `SelectedPool_from_graph.txt`)

### Step 3a – greedy independent set

Core routine: `greedy_independent_set(adj, rng, seed=None)`

Algorithm:

1. Start with:
- `remaining = {0, 1, ..., n-1}` (all nodes),
- `selected = []`.

2. Optionally add a **seed** set of already‑independent nodes.
3. While there are nodes remaining:
- Pick a random node `v` from `remaining`.
- Add `v` to `selected`.
- Remove `v` **and all its neighbors** from `remaining`.

This produces a **maximal** independent set (you can’t add any more nodes without creating conflicts), but not necessarily maximum.

In `main`, the script runs this many times:


```
for round_idx in range(args.rounds):
selected = greedy_independent_set(adj, rng)
if len(selected) > len(best_indices):
best_indices = selected
```
It keeps the largest independent set it has seen so far (`best_indices`).

### Step 3b – optimization pass (`optimize_select_graph`)

To push the size a bit further, there’s a second phase that tries to improve `best_indices`:

- Print “Before optimization: k” where `k = len(best_indices)`.
- If `k == 0`, nothing to do.
- Otherwise:
11365. Set `count_unchanged = 0`.
11366. Repeat while `count_unchanged ≤ 120 * current_size`:
- If current size ≤ 1, break.
- Create a **seed** by dropping the first node:
- Run `greedy_independent_set(adj, rng, seed=seed)`.
- If the new set is **larger**, accept it and reset `count_unchanged = 0`.
- Otherwise, accept it but increment `count_unchanged`.

- You can hit **Ctrl‑C** to stop earlier.

Intuition: “kick out” one sequence and re‑grow greedily: sometimes this lets you escape a local optimum and add more sequences overall.

**Final output:** a large set of **mutually non‑conflicting 9‑nt KL candidates** in `SelectedPool_from_graph.txt`. (Typically, >220 candidates; if you are lucky, >230.)



---

The result is a **large, algorithmically optimized set of 9‑nt KL sequences** that:

- behave nicely on their own,
- don’t bind strongly to the constant handle,
- and are predicted not to bind strongly to each other in any orientation.

## Step 4 – `pool_rna_complement.py`

This final pool is what you feed into tile‑design scripts (2D/3D bricks), which then assign one 9‑nt bulge (with its reverse‑complement loop) to each bKL edge in the structure.

The **tile‑design scripts** expect a **KL pool file** where each non‑empty line has **at least two** RNA sequences, and they treat the **first column** as the 9‑nt bulge sequence.

### How to run it (9‑nt example)

To get a compatible pool file from the graph‑selected list, we run:


```
python pool_rna_complement.py SelectedPool_from_graph.txt
```
- **Input format:** `index<TAB>sequence`
- **Text output format:** `sequence<TAB>reverse_complement_sequence`
  (the second column is reverse-complemented before writing)

The script now produces two outputs:

1. Complement text file (`*_complement.txt`), finalized by the one-command pipeline as:
   - `Orthogonal_RNA_Pool_9nt.txt`
2. Orthogonality figure from pairwise NUPACK free energies:
   - `orthogonality_9nt_RNA_Pool.png`

Example (first lines of `Orthogonal_RNA_Pool_9nt/Orthogonal_RNA_Pool_9nt.txt`):

```text
UAGAGCUAC	GUAGCUCUA
UGAGAGUUC	GAACUCUCA
UACCAUUGC	GCAAUGGUA
UGUACUCAC	GUGAGUACA
CUAGUUACC	GGUAACUAG
GCUACAUAG	CGAUGUAUC
```

Example figure (`orthogonality_9nt_RNA_Pool.png`):

![Orthogonality 9nt RNA Pool](Orthogonal_RNA_Pool_9nt/orthogonality_9nt_RNA_Pool.png)

If NUPACK is unavailable, step 4 still writes the complement text output and prints a warning; the figure is skipped.

NUPACK settings used for the figure:
- `Model(material='rna', celsius=37, sodium=0.1, magnesium=0.010)`
- All pairwise 2-combinations are evaluated.
- Histogram uses bin width `0.2`; On-target and Off-target are plotted separately.


---

## Command Examples

Open the GUI with defaults:

```bash
python run_orthogonal_selection.py
```

Run non-interactively with defaults:

```bash
python run_orthogonal_selection.py --cli
```

Use a different G/C count (five G/C bases in each 9-mer):

```bash
python run_orthogonal_selection.py -N 9 -C 5
```

Runs with different G/C counts but the same `N` use the same output directory
and filenames, so move or rename earlier results before rerunning if you need
to keep both. The GUI warns before reusing an existing output directory.

Set length and rounds:

```bash
python run_orthogonal_selection.py -N 9 -R 2000
```

Use multiple guides:

```bash
python run_orthogonal_selection.py -N 9 -G CACGAAGUCAAUAC -G GGGAAAUUU
```

Set custom final output filename:

```bash
python run_orthogonal_selection.py -N 9 -O My_Final_Pool.txt
```
This changes only the step-4 text file name. The figure is still generated as:
`orthogonality_9nt_RNA_Pool.png`.

Show help/instructions:

```bash
python run_orthogonal_selection.py --help
python run_orthogonal_selection.py -U
```

---

## Folder Layout

- `run_orthogonal_selection.py`: GUI/CLI entry point, parameter-entry window, live log, and pipeline runner.
- `functions/generate_pool_nnt.py`: step 1 implementation.
- `functions/build_rna_conflict_graphV2.py`: step 2 implementation.
- `functions/select_from_conflict_graph.py`: step 3 implementation.
- `functions/pool_rna_complement.py`: step 4 implementation.
- `Orthogonal_RNA_Pool_9nt/`: example output folder.
