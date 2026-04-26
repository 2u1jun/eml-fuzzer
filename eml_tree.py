"""
eml_tree.py — EML tree data structure and random generator

eml(x, y) = exp(x) - ln(y)
Grammar: S -> 1 | eml(S, S)
"""

from __future__ import annotations
import random
import math
from dataclasses import dataclass
from typing import Union


# ── Node types ─────────────────────────────────────────────
@dataclass
class Leaf:
    """Terminal node: the constant 1."""
    def __repr__(self):
        return "1"

    def depth(self) -> int:
        return 0

    def node_count(self) -> int:
        return 1

    def to_expr(self) -> str:
        return "1"


@dataclass
class EMLNode:
    """Internal node: eml(left, right) = exp(left) - ln(right)"""
    left: "EMLTree"
    right: "EMLTree"

    def __repr__(self):
        return f"eml({self.left}, {self.right})"

    def depth(self) -> int:
        return 1 + max(self.left.depth(), self.right.depth())

    def node_count(self) -> int:
        return 1 + self.left.node_count() + self.right.node_count()

    def to_expr(self) -> str:
        return f"eml({self.left.to_expr()}, {self.right.to_expr()})"


EMLTree = Union[Leaf, EMLNode]


# ── Random tree generation ──────────────────────────────────
def random_eml_tree(max_depth: int, rng: random.Random = None) -> EMLTree:
    """
    Generate a random EML tree up to max_depth.
    Returns a Leaf when max_depth == 0.
    """
    if rng is None:
        rng = random.Random()

    if max_depth == 0:
        return Leaf()

    # Increase leaf probability as depth grows to prevent exponential blowup
    leaf_prob = 1.0 / (max_depth + 1)
    if rng.random() < leaf_prob:
        return Leaf()

    left  = random_eml_tree(max_depth - 1, rng)
    right = random_eml_tree(max_depth - 1, rng)
    return EMLNode(left, right)


def generate_batch(
    count: int,
    min_depth: int = 1,
    max_depth: int = 10,
    seed: int = None,
) -> list[EMLTree]:
    """
    Generate `count` random EML trees.
    Depth is sampled uniformly from [min_depth, max_depth].
    """
    rng   = random.Random(seed)
    trees = []
    for _ in range(count):
        depth = rng.randint(min_depth, max_depth)
        trees.append(random_eml_tree(depth, rng))
    return trees


# ── Numeric evaluation ─────────────────────────────────────
def eval_tree(tree: EMLTree, x: float = 1.0) -> float:
    """
    Evaluate a tree to a float.
    Returns None on domain errors (ln of non-positive, overflow).
    The `x` parameter is reserved for future variable support.
    """
    if isinstance(tree, Leaf):
        return 1.0

    lv = eval_tree(tree.left, x)
    rv = eval_tree(tree.right, x)

    if lv is None or rv is None:
        return None
    if rv <= 0:
        return None  # ln domain error: argument must be positive

    try:
        result = math.exp(lv) - math.log(rv)
        if not math.isfinite(result):
            return None
        return result
    except (OverflowError, ValueError):
        return None


# ── Statistics ─────────────────────────────────────────────
def tree_stats(trees: list[EMLTree]) -> dict:
    depths = [t.depth() for t in trees]
    nodes  = [t.node_count() for t in trees]
    return {
        "count":      len(trees),
        "depth_min":  min(depths),
        "depth_max":  max(depths),
        "depth_avg":  sum(depths) / len(depths),
        "nodes_min":  min(nodes),
        "nodes_max":  max(nodes),
        "nodes_avg":  sum(nodes) / len(nodes),
    }


# ── Quick smoke test ───────────────────────────────────────
if __name__ == "__main__":
    print("=== EML Tree Generation Test ===\n")

    # Print 5 small trees
    for i, tree in enumerate(generate_batch(5, min_depth=1, max_depth=4, seed=42)):
        val     = eval_tree(tree)
        val_str = f"{val:.4f}" if val is not None else "NaN/Inf (domain error)"
        print(f"[{i+1}] depth={tree.depth():2d}  nodes={tree.node_count():3d}  eval={val_str}")
        expr = tree.to_expr()
        print(f"     {expr[:80]}{'...' if len(expr) > 80 else ''}\n")

    # Large batch statistics
    batch = generate_batch(1000, min_depth=1, max_depth=15, seed=0)
    stats = tree_stats(batch)
    print("=== Batch statistics (n=1000) ===")
    for k, v in stats.items():
        print(f"  {k}: {v:.1f}" if isinstance(v, float) else f"  {k}: {v}")