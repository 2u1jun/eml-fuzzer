"""
fuzzer.py — EML tree fuzzer targeting CAS engines (multiprocessing)

Attack vectors:
  1. Timeout / Hang   — simplify() stalls indefinitely on deep EML trees
  2. RecursionError   — SymPy internals exceed Python's recursion limit
  3. Wrong Answer     — symbolic result disagrees with numeric evaluation
  4. Crash            — unexpected exception from SymPy

Multiprocessing design:
  - Each test case runs in an isolated subprocess
  - Timed-out workers are killed with process.terminate() (no SIGALRM needed)
  - Works on Linux, macOS, and Windows
"""

from __future__ import annotations
import math
import time
import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Optional

import sympy as sp

from eml_tree import EMLTree, Leaf, EMLNode, generate_batch, eval_tree


# ── Bug report ─────────────────────────────────────────────
@dataclass
class BugReport:
    kind: str          # "timeout" | "recursion" | "wrong_answer" | "crash" | "slow"
    depth: int
    node_count: int
    expr_str: str
    detail: str
    duration_sec: float = 0.0
    numeric_expected: Optional[float] = None
    sympy_got: Optional[str] = None


# ── Worker function (runs in a separate process) ────────────
def _worker(tree_data: dict, result_queue: mp.Queue):
    """
    Spawned as a child process for each test case.
    If this process hangs, the parent kills it after timeout_sec.
    """
    import sympy as sp
    import math, time

    expr_str    = tree_data["expr_str"]
    depth       = tree_data["depth"]
    nodes       = tree_data["node_count"]
    numeric_val = tree_data["numeric_val"]

    def parse_eml(s: str) -> sp.Expr:
        """Recursively parse an EML expression string into a SymPy Expr."""
        s = s.strip()
        if s == "1":
            return sp.Integer(1)
        assert s.startswith("eml(") and s.endswith(")")
        inner = s[4:-1]
        level = 0
        for i, ch in enumerate(inner):
            if ch == "(":   level += 1
            elif ch == ")": level -= 1
            elif ch == "," and level == 0:
                # Split at the top-level comma
                left  = parse_eml(inner[:i])
                right = parse_eml(inner[i+1:])
                return sp.exp(left) - sp.log(right)
        raise ValueError(f"Parse failed: {s}")

    t0 = time.perf_counter()
    try:
        sympy_expr       = parse_eml(expr_str)
        sympy_simplified = sp.simplify(sympy_expr)   # <-- this is where hangs occur
        elapsed          = time.perf_counter() - t0

        # Differential testing: compare numeric value vs symbolic result
        if numeric_val is not None:
            try:
                sf = float(sympy_simplified.evalf())
                if math.isfinite(sf):
                    rel_err = abs(sf - numeric_val) / (abs(numeric_val) + 1e-12)
                    if rel_err > 1e-6:
                        result_queue.put(BugReport(
                            kind="wrong_answer",
                            depth=depth, node_count=nodes, expr_str=expr_str,
                            detail=f"numeric={numeric_val:.6g}  sympy={sf:.6g}  rel_err={rel_err:.2e}",
                            duration_sec=elapsed,
                            numeric_expected=numeric_val,
                            sympy_got=str(sympy_simplified),
                        ))
                        return
            except Exception:
                pass  # evalf failure is not classified as wrong_answer

        # Flag slow cases as potential DoS vectors
        if elapsed > 2.0:
            result_queue.put(BugReport(
                kind="slow",
                depth=depth, node_count=nodes, expr_str=expr_str,
                detail=f"simplify() took {elapsed:.2f}s",
                duration_sec=elapsed,
            ))
            return

        result_queue.put(None)  # clean — no bug found

    except RecursionError:
        elapsed = time.perf_counter() - t0
        result_queue.put(BugReport(
            kind="recursion",
            depth=depth, node_count=nodes, expr_str=expr_str,
            detail="RecursionError — Python recursion limit exceeded inside SymPy",
            duration_sec=elapsed,
        ))
    except Exception as e:
        elapsed = time.perf_counter() - t0
        result_queue.put(BugReport(
            kind="crash",
            depth=depth, node_count=nodes, expr_str=expr_str,
            detail=f"{type(e).__name__}: {str(e)[:120]}",
            duration_sec=elapsed,
        ))


# ── Batch fuzzing (parallel) ───────────────────────────────
@dataclass
class FuzzResult:
    total: int = 0
    clean: int = 0
    bugs: list[BugReport] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def summary(self) -> str:
        lines = [
            f"\n{'='*55}",
            f"  Total cases  : {self.total}",
            f"  Clean        : {self.clean}",
            f"  Bugs found   : {len(self.bugs)}",
            f"  Elapsed      : {self.elapsed_sec:.1f}s",
            f"{'='*55}",
        ]
        if self.bugs:
            by_kind: dict[str, list] = {}
            for b in self.bugs:
                by_kind.setdefault(b.kind, []).append(b)
            for kind, items in sorted(by_kind.items()):
                lines.append(f"\n  [{kind.upper()}] — {len(items)} case(s)")
                for b in items[:5]:
                    lines.append(f"    depth={b.depth:2d}  nodes={b.node_count:4d}  {b.detail}")
        return "\n".join(lines)


def fuzz(
    count: int = 100,
    min_depth: int = 3,
    max_depth: int = 12,
    timeout_sec: int = 5,
    workers: int = None,
    seed: int = None,
    verbose: bool = True,
) -> FuzzResult:
    """
    Generate `count` random EML trees and attack SymPy with them.

    Args:
        count:       Number of test cases
        min_depth:   Minimum tree depth
        max_depth:   Maximum tree depth (depth 7+ reliably triggers timeouts)
        timeout_sec: Per-case timeout; worker process is killed if exceeded
        workers:     Parallel worker count (defaults to CPU core count)
        seed:        Random seed for reproducibility
        verbose:     Print progress to stdout
    """
    if workers is None:
        workers = mp.cpu_count()

    trees  = generate_batch(count, min_depth, max_depth, seed=seed)
    result = FuzzResult(total=count)
    t0     = time.perf_counter()

    # Process trees in batches of `workers` — each batch runs in parallel
    for batch_start in range(0, len(trees), workers):
        batch = trees[batch_start : batch_start + workers]

        # Launch all workers in this batch simultaneously
        jobs = []
        for tree in batch:
            td = {
                "expr_str":    tree.to_expr(),
                "depth":       tree.depth(),
                "node_count":  tree.node_count(),
                "numeric_val": eval_tree(tree),
            }
            q = mp.Queue()
            p = mp.Process(target=_worker, args=(td, q))
            p.start()
            jobs.append((p, q, tree, time.perf_counter()))

        # Collect results; kill any worker that exceeds timeout
        for p, q, tree, launch_time in jobs:
            remaining = timeout_sec - (time.perf_counter() - launch_time)
            p.join(timeout=max(0.1, remaining))

            if p.is_alive():
                # Hard kill — SymPy's GIL-holding simplify() cannot be interrupted otherwise
                p.terminate()
                p.join()
                bug = BugReport(
                    kind="timeout",
                    depth=tree.depth(),
                    node_count=tree.node_count(),
                    expr_str=tree.to_expr(),
                    detail=f"exceeded {timeout_sec}s — process killed",
                    duration_sec=float(timeout_sec),
                )
                result.bugs.append(bug)
                if verbose:
                    print(f"  💀 TIMEOUT      depth={tree.depth():2d}  nodes={tree.node_count():4d}")
            else:
                bug = q.get() if not q.empty() else None
                if bug:
                    result.bugs.append(bug)
                    if verbose:
                        icon = {
                            "slow":        "🐢",
                            "wrong_answer":"❌",
                            "recursion":   "💥",
                            "crash":       "🔥",
                        }.get(bug.kind, "⚠️")
                        print(f"  {icon} {bug.kind.upper():12s} depth={bug.depth:2d}  nodes={bug.node_count:4d}  {bug.detail}")
                else:
                    result.clean += 1

        done = batch_start + len(batch)
        if verbose:
            print(f"  ── [{done:3d}/{count}] done  bugs={len(result.bugs)} ──")

    result.elapsed_sec = time.perf_counter() - t0
    return result


# ── CLI ────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="EML CAS Fuzzer — stress-test SymPy with EML trees"
    )
    parser.add_argument("-n", "--count",   type=int, default=50,   help="number of test cases (default: 50)")
    parser.add_argument("--min-depth",     type=int, default=3,    help="minimum tree depth (default: 3)")
    parser.add_argument("--max-depth",     type=int, default=10,   help="maximum tree depth (default: 10)")
    parser.add_argument("--timeout",       type=int, default=5,    help="per-case timeout in seconds (default: 5)")
    parser.add_argument("--workers",       type=int, default=None, help="parallel worker count (default: CPU cores)")
    parser.add_argument("--seed",          type=int, default=None, help="random seed")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════╗
║        EML CAS Fuzzer v0.1           ║
║  Stress-testing SymPy with EML trees ║
╚══════════════════════════════════════╝
  cases    : {args.count}
  depth    : {args.min_depth} ~ {args.max_depth}
  timeout  : {args.timeout}s per case
  workers  : {args.workers or mp.cpu_count()} (CPU has {mp.cpu_count()} cores)
""")

    result = fuzz(
        count=args.count,
        min_depth=args.min_depth,
        max_depth=args.max_depth,
        timeout_sec=args.timeout,
        workers=args.workers,
        seed=args.seed,
        verbose=True,
    )
    print(result.summary())
