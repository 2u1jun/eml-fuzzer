# eml-fuzzer 🔨

> **A fuzzer that attacks Computer Algebra Systems (CAS) using EML trees**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Odrzywolek (2026)](https://arxiv.org/abs/2603.21852) proved that the single binary operator  
`eml(x, y) = exp(x) − ln(y)`, combined with the constant `1`, can express every standard elementary function.

This project turns that mathematical elegance into a weapon.  
EML trees are **mathematically valid** yet structurally brutal — depth-7 trees already cause SymPy's `simplify()` to hang indefinitely.

---

## Why EML fuzzing?

| | csmith / AFL | **eml-fuzzer** |
|---|---|---|
| Target | GCC, LLVM (compilers) | SymPy, Mathematica (CAS engines) |
| Input | Random bytes / C code | Mathematically valid EML trees |
| Bugs found | Memory corruption, codegen | **simplify() hangs, recursion crashes, float mismatches** |

EML trees have a single uniform grammar: `S → 1 | eml(S, S)`  
This makes random generation trivial while producing inputs that CAS engines have never been stress-tested against.

---

## Quickstart

```bash
git clone https://github.com/YOUR_USERNAME/eml-fuzzer
cd eml-fuzzer
pip install sympy
```

---

## Usage

### Step 1 — Fuzz (`fuzzer.py`)

Find bugs by hammering SymPy with random EML trees.

```bash
# Basic run — 50 cases, depth 3~10, 5s timeout
python fuzzer.py

# Crank it up
python fuzzer.py -n 200 --min-depth 5 --max-depth 12 --timeout 8 --workers 4

# Reproducible run
python fuzzer.py -n 100 --seed 1337
```

```
╔══════════════════════════════════════╗
║        EML CAS Fuzzer v0.1           ║
║  Stress-testing SymPy with EML trees ║
╚══════════════════════════════════════╝
  cases    : 50
  depth    : 3 ~ 10
  timeout  : 5s per case
  workers  : 4 (CPU has 8 cores)

  💀 TIMEOUT      depth= 8  nodes= 111
  💀 TIMEOUT      depth= 7  nodes=  99
  🐢 SLOW         depth= 7  nodes=  87  simplify() took 2.55s
  ── [ 50/50] done  bugs=8 ──
```

### Step 2 — Minimize (`minimizer.py`)

Reduce a crashing tree to its **smallest possible reproducer**, then generate a  
ready-to-paste GitHub issue report.

```bash
python minimizer.py
```

```
Step 1: Finding a bug to minimize...

Bug found: [timeout] depth=5 nodes=45

Step 2: Minimizing...

Minimizing [TIMEOUT]  start: depth=5  nodes=45
  pass 1: 22 internal nodes to try
    ✂  node 7 pruned  -> depth=5  nodes=43
  pass 2: 21 internal nodes to try
    ✂  node 8 pruned  -> depth=5  nodes=37
  ...
Minimization complete.
  Original : depth=5  nodes=45
  Minimized: depth=5  nodes=13
  Reduction: 71.1%

Step 3: GitHub issue draft
============================================================
## `simplify()` timeout on deeply nested exp/log expression

**SymPy version:** `1.14.0`
**Bug class:** `timeout`
**Minimal tree:** depth=5, nodes=13

### Minimal Reproducible Example

from sympy import *
x = exp(exp(exp(exp(exp(Integer(1)) - log(Integer(1))) - log(Integer(1))) \
         - log(Integer(1))) - log(Integer(1))) \
  - log(exp(Integer(1)) - log(Integer(1)))
simplify(x)   # hangs / never returns
============================================================
```

**The output is a complete GitHub issue draft.** Copy it directly to a SymPy issue report.

### Use as a library

```python
from eml_tree import generate_batch
from fuzzer import fuzz
from minimizer import minimize, generate_issue_report

# 1. Find bugs
result = fuzz(count=200, min_depth=4, max_depth=12, timeout_sec=5, workers=4)

# 2. Minimize the first bug found
if result.bugs:
    from eml_tree import random_eml_tree
    # re-run with seed to recover the crashing tree, then:
    minimized = minimize(crashing_tree, result.bugs[0], timeout_sec=5)
    print(generate_issue_report(minimized, result.bugs[0]))
```

---

## How it works

### 1. Tree Generation (`eml_tree.py`)

Random EML trees are generated according to the grammar `S → 1 | eml(S, S)`.

```
depth=7, nodes=99  → sin(x) alone requires 543 nodes in pure EML form
depth=8, nodes=169 → SymPy simplify() timeout (confirmed)
```

### 2. Attack Vectors (`fuzzer.py`)

| Bug class | Description |
|-----------|-------------|
| `timeout` | `simplify()` exceeds time limit — process is hard-killed |
| `slow` | `simplify()` takes >2s — potential DoS vector |
| `recursion` | Python `RecursionError` inside SymPy internals |
| `wrong_answer` | Numeric value ≠ symbolic result (differential testing) |
| `crash` | Unexpected exception from SymPy |

### 3. Multiprocessing (`fuzzer.py`)

Each test case runs in an **isolated subprocess**.  
Timed-out workers are killed with `process.terminate()` — no SIGALRM, works on Linux, macOS, and Windows.

### 4. Minimizer (`minimizer.py`)

Greedy top-down delta-debugging: repeatedly replace subtrees with `Leaf(1)`,  
keeping reductions that preserve the bug. Typically achieves **60–80% node reduction**.

---

## Results

Running `python fuzzer.py -n 30 --max-depth 8 --seed 1337`:

```
  Total cases  : 30
  Clean        : 22
  Bugs found   : 8   (27% bug rate)

  [TIMEOUT] — 7 cases
    depth= 7  nodes= 99
    depth= 7  nodes=117
    depth= 8  nodes=157

  [SLOW] — 1 case
    depth= 7  nodes= 87   simplify() took 2.55s
```

---

## Project Structure

```
eml-fuzzer/
├── eml_tree.py    # EML tree data structure + random generator
├── fuzzer.py      # CAS attack engine (multiprocessing)
├── minimizer.py   # Delta-debugging minimizer + GitHub issue generator
└── README.md
```

---

## CLI Reference

**fuzzer.py**
```
  -n, --count       Number of test cases (default: 50)
  --min-depth       Minimum tree depth (default: 3)
  --max-depth       Maximum tree depth (default: 10)
  --timeout         Per-case timeout in seconds (default: 5)
  --workers         Parallel worker count (default: CPU core count)
  --seed            Random seed for reproducibility
```

**minimizer.py**  
Run directly — finds one bug, minimizes it, and prints a GitHub issue draft.

---

## Roadmap

- [x] Random EML tree generator
- [x] Multiprocessing fuzzer with hard timeout
- [x] Differential testing (numeric vs symbolic)
- [x] Delta-debugging minimizer
- [x] Automatic GitHub issue report generation
- [ ] SageMath / Mathematica target support
- [ ] Seed corpus for known slow patterns
- [ ] CI regression tracking

---

## Reference

- Odrzywolek, A. (2026). *All elementary functions from a single operator*. [arXiv:2603.21852](https://arxiv.org/abs/2603.21852)

---

## License

MIT
