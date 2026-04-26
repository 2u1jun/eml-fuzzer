# eml-fuzzer 🔨

> **A fuzzer that attacks Computer Algebra Systems (CAS) using EML trees**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Odrzywolek (2026)](https://arxiv.org/abs/2603.21852) proved that the single binary operator  
`eml(x, y) = exp(x) − ln(y)`, combined with the constant `1`, can express every standard elementary function.

This project turns that mathematical elegance into a weapon.  
EML trees are **mathematically valid** yet structurally brutal — and depth-7 trees already cause SymPy's `simplify()` to hang indefinitely.

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

### Run the fuzzer

```bash
# Basic run — 50 cases, depth 3~10, 5s timeout
python fuzzer.py

# Custom run
python fuzzer.py -n 200 --min-depth 5 --max-depth 12 --timeout 8 --workers 4

# Reproducible run with seed
python fuzzer.py -n 100 --seed 1337
```

### Use as a library

```python
from eml_tree import generate_batch
from fuzzer import fuzz

result = fuzz(
    count=200,
    min_depth=4,
    max_depth=12,
    timeout_sec=5,
    workers=4,        # parallel workers = CPU cores
    seed=42,
)
print(result.summary())
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

### 3. Multiprocessing

Each test case runs in an **isolated subprocess**.  
Timed-out workers are killed with `process.terminate()` — no SIGALRM, works on all OS.

```
workers=4 → 4 EML trees attack SymPy simultaneously
```

---

## Results so far

Running `python fuzzer.py -n 30 --max-depth 8 --seed 1337`:

```
=======================================================
  Total cases  : 30
  Clean        : 22
  Bugs found   : 8
  Elapsed      : 31.3s
=======================================================

  [TIMEOUT] — 7 cases
    depth= 7  nodes= 99   exceeded 5s limit
    depth= 7  nodes=117   exceeded 5s limit
    depth= 8  nodes=157   exceeded 5s limit

  [SLOW] — 1 case
    depth= 7  nodes= 87   simplify() took 2.55s
```

**27% bug rate at depth 7~8.** SymPy's simplify() cannot handle moderately deep EML trees.

---

## Project Structure

```
eml-fuzzer/
├── eml_tree.py    # EML tree data structure + random generator
├── fuzzer.py      # CAS attack engine (multiprocessing)
└── README.md
```

---

## CLI Reference

```
usage: fuzzer.py [-h] [-n COUNT] [--min-depth MIN_DEPTH] [--max-depth MAX_DEPTH]
                 [--timeout TIMEOUT] [--workers WORKERS] [--seed SEED]

options:
  -n, --count       Number of test cases (default: 50)
  --min-depth       Minimum tree depth (default: 3)
  --max-depth       Maximum tree depth (default: 10)
  --timeout         Per-case timeout in seconds (default: 5)
  --workers         Parallel worker count (default: CPU core count)
  --seed            Random seed for reproducibility
```

---

## Roadmap

- [ ] SageMath / Mathematica support
- [ ] Automatic SymPy issue report generation
- [ ] RecursionError trigger at controlled depth
- [ ] Minimizer: reduce crashing tree to smallest reproducer
- [ ] CI integration for regression tracking

---

## Reference

- Odrzywolek, A. (2026). *All elementary functions from a single operator*. [arXiv:2603.21852](https://arxiv.org/abs/2603.21852)

---

## License

MIT
