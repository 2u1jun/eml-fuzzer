"""
minimizer.py — Reduce a bug-triggering EML tree to its smallest reproducer

Given a large EML tree that causes a timeout/crash/wrong_answer in SymPy,
the minimizer systematically prunes branches until it finds the smallest
subtree that still reproduces the same bug class.

Algorithm: greedy top-down pruning (delta-debugging style)
  1. Try replacing each subtree with a Leaf (constant 1)
  2. If the bug still occurs -> keep the pruned version
  3. Repeat until no further reduction is possible
"""

from __future__ import annotations
import time
import multiprocessing as mp
from typing import Optional

from eml_tree import EMLTree, Leaf, EMLNode, eval_tree
from fuzzer import BugReport, _worker


# ── Single-case attack (reused from fuzzer, standalone) ────
def _attack(tree: EMLTree, timeout_sec: int) -> Optional[BugReport]:
    """Run one tree against SymPy and return a BugReport or None."""
    td = {
        "expr_str":    tree.to_expr(),
        "depth":       tree.depth(),
        "node_count":  tree.node_count(),
        "numeric_val": eval_tree(tree),
    }
    q = mp.Queue()
    p = mp.Process(target=_worker, args=(td, q))
    p.start()
    p.join(timeout=timeout_sec)

    if p.is_alive():
        p.terminate()
        p.join()
        return BugReport(
            kind="timeout",
            depth=tree.depth(),
            node_count=tree.node_count(),
            expr_str=tree.to_expr(),
            detail=f"exceeded {timeout_sec}s — process killed",
            duration_sec=float(timeout_sec),
        )

    return q.get() if not q.empty() else None


# ── Tree surgery helpers ────────────────────────────────────
def _replace_at(tree: EMLTree, target_id: int, replacement: EMLTree,
                counter: list) -> EMLTree:
    """
    Return a copy of `tree` where the node with pre-order index `target_id`
    is replaced by `replacement`.
    counter[0] tracks the current pre-order index during traversal.
    """
    my_id = counter[0]
    counter[0] += 1

    if my_id == target_id:
        return replacement

    if isinstance(tree, Leaf):
        return tree

    left  = _replace_at(tree.left,  target_id, replacement, counter)
    right = _replace_at(tree.right, target_id, replacement, counter)
    return EMLNode(left, right)


def replace_node(tree: EMLTree, target_id: int, replacement: EMLTree) -> EMLTree:
    """Public wrapper for _replace_at."""
    return _replace_at(tree, target_id, replacement, [0])


def collect_node_ids(tree: EMLTree, ids: list = None) -> list[int]:
    """Return pre-order indices of all internal (non-Leaf) nodes."""
    if ids is None:
        ids = []
    counter = [0]

    def walk(node: EMLTree):
        my_id = counter[0]
        counter[0] += 1
        if isinstance(node, EMLNode):
            ids.append(my_id)
            walk(node.left)
            walk(node.right)

    walk(tree)
    return ids


# ── Core minimizer ─────────────────────────────────────────
def minimize(
    original_tree: EMLTree,
    original_bug: BugReport,
    timeout_sec: int = 5,
    verbose: bool = True,
) -> EMLTree:
    """
    Reduce `original_tree` to the smallest tree that reproduces
    the same bug class as `original_bug`.

    Strategy: one pass over all internal nodes in pre-order.
    For each node, try replacing it with a Leaf.
    If the same bug class reappears -> accept the reduction and continue.

    Returns the minimized tree (always smaller than or equal to original).
    """
    bug_kind = original_bug.kind
    current  = original_tree

    if verbose:
        print(f"Minimizing [{bug_kind.upper()}]  "
              f"start: depth={current.depth()}  nodes={current.node_count()}")

    improved = True
    iteration = 0

    while improved:
        improved  = False
        iteration += 1
        node_ids  = collect_node_ids(current)

        if verbose:
            print(f"  pass {iteration}: {len(node_ids)} internal nodes to try")

        for nid in node_ids:
            candidate = replace_node(current, nid, Leaf())

            # Skip if no actual reduction happened
            if candidate.node_count() >= current.node_count():
                continue

            bug = _attack(candidate, timeout_sec=timeout_sec)

            if bug is not None and bug.kind == bug_kind:
                # Bug still present after pruning -> accept
                current  = candidate
                improved = True
                if verbose:
                    print(f"    ✂  node {nid} pruned  "
                          f"-> depth={current.depth()}  nodes={current.node_count()}")
                # Restart node list since tree structure changed
                break

    if verbose:
        print(f"\nMinimization complete.")
        print(f"  Original : depth={original_tree.depth()}  "
              f"nodes={original_tree.node_count()}")
        print(f"  Minimized: depth={current.depth()}  "
              f"nodes={current.node_count()}")
        reduction = (1 - current.node_count() / original_tree.node_count()) * 100
        print(f"  Reduction: {reduction:.1f}%")

    return current


# ── GitHub issue report generator ──────────────────────────
def generate_issue_report(
    minimized_tree: EMLTree,
    bug: BugReport,
    sympy_version: str = None,
) -> str:
    """
    Generate a ready-to-paste GitHub issue report for a minimized bug.
    """
    import sympy as sp
    if sympy_version is None:
        sympy_version = sp.__version__

    # Build the SymPy repr of the minimized tree
    def to_sympy_repr(tree: EMLTree) -> str:
        if isinstance(tree, Leaf):
            return "Integer(1)"
        l = to_sympy_repr(tree.left)
        r = to_sympy_repr(tree.right)
        return f"exp({l}) - log({r})"

    sympy_code = to_sympy_repr(minimized_tree)

    report = f"""## `simplify()` {bug.kind} on deeply nested exp/log expression

**SymPy version:** `{sympy_version}`  
**Bug class:** `{bug.kind}`  
**Minimal tree:** depth={minimized_tree.depth()}, nodes={minimized_tree.node_count()}

### Minimal Reproducible Example

```python
from sympy import *
x = {sympy_code}
simplify(x)   # {_bug_expectation(bug.kind)}
```

### Details

{bug.detail}

### Context

This bug was discovered using [eml-fuzzer](https://github.com/YOUR_USERNAME/eml-fuzzer),
a fuzzer that stress-tests CAS engines with deeply nested EML operator trees
(`eml(x, y) = exp(x) - ln(y)`), as introduced in [arXiv:2603.21852](https://arxiv.org/abs/2603.21852).

The expression above is the **minimized** form. The original crashing tree had
{bug.node_count} nodes; this reproducer has {minimized_tree.node_count()}.
"""
    return report


def _bug_expectation(kind: str) -> str:
    return {
        "timeout":      "hangs / never returns",
        "slow":         "takes unexpectedly long",
        "recursion":    "raises RecursionError",
        "crash":        "raises unexpected exception",
        "wrong_answer": "returns incorrect result",
    }.get(kind, "triggers bug")


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    """
    Demo: fuzz for one bug, then minimize and print the GitHub issue draft.
    """
    from eml_tree import generate_batch
    from fuzzer import fuzz

    print("Step 1: Finding a bug to minimize...\n")
    trees = generate_batch(30, min_depth=5, max_depth=9, seed=999)

    bug_tree  = None
    bug_report = None

    for tree in trees:
        report = _attack(tree, timeout_sec=5)
        if report is not None:
            bug_tree   = tree
            bug_report = report
            print(f"Bug found: [{report.kind}] depth={tree.depth()} nodes={tree.node_count()}")
            print(f"  {report.detail}\n")
            break

    if bug_tree is None:
        print("No bug found in this seed. Try increasing max_depth.")
    else:
        print("Step 2: Minimizing...\n")
        minimized = minimize(bug_tree, bug_report, timeout_sec=5, verbose=True)

        print("\nStep 3: GitHub issue draft\n")
        print("=" * 60)
        print(generate_issue_report(minimized, bug_report))
        print("=" * 60)
