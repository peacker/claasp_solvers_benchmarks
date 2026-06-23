"""First-class taxonomy dimensions for CLAASP benchmark challenges."""

from __future__ import annotations

TAXONOMY = {
    "goal": [
        "find_one_trail",
        "prove_bound",
        "enumerate_trails",
        "estimate_probability",
        "key_recovery",
        "hash_collision",
    ],
    "primitive_family": [
        "ARX",
        "word_based_SPN",
        "bit_based_SPN",
        "Feistel",
        "permutation",
        "hash_component",
    ],
    "analysis": [
        "differential",
        "linear",
        "differential_linear",
        "rotational_xor",
        "impossible_differential",
        "integral",
    ],
    "model_family": [
        "SAT",
        "SMT",
        "MILP",
        "CP_MiniZinc",
        "algebraic",
        "hybrid",
    ],
    "difficulty": [
        "tutorial",
        "benchmark",
        "boundary",
        "open_challenge",
    ],
    "io_mode": [
        "fixed_io",
        "free_io",
    ],
    "model_mode": [
        "fixed_model",
        "free_model",
    ],
}

RESULT_STATUSES = ["sat", "unsat", "optimum", "timeout", "error", "unknown", "skipped"]


def allowed_values(field: str) -> list[str]:
    return list(TAXONOMY[field])
