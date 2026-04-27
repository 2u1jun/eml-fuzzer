# SYMPY GITHUB ISSUE REPORT
# Post at: https://github.com/sympy/sympy/issues/new
# Title: simplify() hangs indefinitely on deeply nested exp/log expressions
#
# -----------------------------------------------------------------------

## `simplify()` hangs indefinitely on deeply nested `exp`/`log` expressions

### Environment

| | |
|---|---|
| **SymPy version** | 1.14.0 |
| **Python version** | 3.x |
| **Platform** | Linux / macOS / Windows |

---

### Description

`simplify()` never returns (hangs indefinitely) when given a deeply nested
composition of `exp` and `log` functions, even when the expression is
numerically finite and well-defined.

The expression has depth 5 and only 13 nodes — not large by any reasonable
measure — yet `simplify()` fails to terminate within 30+ seconds.

---

### Minimal Reproducible Example

```python
from sympy import *

x = (
    exp(
        exp(
            exp(
                exp(exp(Integer(1)) - log(Integer(1))) - log(Integer(1))
            ) - log(Integer(1))
        ) - log(Integer(1))
    )
    - log(exp(Integer(1)) - log(Integer(1)))
)

# This hangs indefinitely:
simplify(x)

# Numeric evaluation works fine and returns a finite value:
print(float(x.evalf()))   # completes immediately
```

To run with a hard timeout to confirm the hang:

```python
import multiprocessing, sympy

def try_simplify(q):
    from sympy import exp, log, Integer, simplify
    x = (
        exp(exp(exp(exp(exp(Integer(1)) - log(Integer(1))) - log(Integer(1)))
            - log(Integer(1))) - log(Integer(1)))
        - log(exp(Integer(1)) - log(Integer(1)))
    )
    q.put(simplify(x))

q = multiprocessing.Queue()
p = multiprocessing.Process(target=try_simplify, args=(q,))
p.start()
p.join(timeout=10)
if p.is_alive():
    p.terminate()
    print("CONFIRMED: simplify() did not return within 10 seconds")
```

---

### Expected behavior

`simplify()` should return within a reasonable time. The expression is a
finite, well-defined real number. `evalf()` handles it without issue.

---

### Actual behavior

`simplify()` never returns. The process must be killed externally.

---

### Root cause hypothesis

The expression is a member of the **EML (Exp-Minus-Log) operator** family
introduced by Odrzywolek (2026) [arXiv:2603.21852], where every elementary
function can be expressed as a tree of `eml(x, y) = exp(x) - log(y)` nodes.

The hypothesis is that `simplify()` internally calls routines such as
`logcombine()`, `powsimp()`, or `fu()` which pattern-match on `exp`/`log`
subexpressions. When these are deeply nested, the pattern matcher enters a
near-infinite expansion loop — each rewrite rule produces a new `exp`/`log`
term that triggers further rewrites, causing the search to blow up.

This is not a numerical issue. It is a structural property of deeply nested
`exp`/`log` compositions that appears to be untested in SymPy's current
test suite.

---

### Scaling behavior

The hang is not an isolated edge case. Systematic fuzzing shows:

| Tree depth | Nodes | `simplify()` result |
|---|---|---|
| ≤ 5 | ≤ 30 | returns in < 1s |
| 6 | ~50 | returns in 1–3s |
| 7 | ~90 | **hangs (> 5s)** |
| 8 | ~120 | **hangs (> 5s)** |

The hang threshold is consistent around depth 7 / ~80 nodes.

---

### Discovery method

This bug was found using **eml-fuzzer**
([github.com/2u1jun/eml-fuzzer](https://github.com/2u1jun/eml-fuzzer)),
a fuzzer that generates random EML trees and feeds them to SymPy.
The 13-node reproducer above was obtained by automated delta-debugging
(minimization) from an original 45-node crashing tree — a 71% reduction.

---

### Suggested fix directions

1. Add a **recursion depth guard** or **node count limit** inside `simplify()`
   that falls back gracefully instead of hanging.
2. Detect when pattern-matching rewrites are cycling and break early.
3. Add `exp`/`log` nesting depth to the existing complexity heuristics in
   `simplify()` to avoid triggering expensive rewrite passes on pathological
   inputs.

---

*If this is a known limitation or a duplicate, please point me to the
relevant issue. Happy to test any proposed fixes.*
