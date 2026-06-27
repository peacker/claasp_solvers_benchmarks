"""First-class taxonomy dimensions for CLAASP benchmark challenges."""

from __future__ import annotations

TAXONOMY = {
    # challenge fields
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
    # execution fields
    "runner": [
        "docker",
        "synthetic",
    ],
    "kind": [
        "claasp_import_check",
        "claasp_cipher_metadata",
        "claasp_xor_differential_find_one",
        "claasp_sat_xor_differential_find_one",
        "claasp_xor_differential_enumerate_fixed_weight",
        "claasp_sat_xor_differential_enumerate_fixed_weight",
        "claasp_xor_differential_find_lowest_weight",
        "claasp_xor_linear_find_one",
        "claasp_xor_linear_enumerate_fixed_weight",
        "claasp_xor_linear_find_lowest_weight",
        "synthetic",
    ],
    "solver_family": [
        "sat",
        "smt",
        "milp",
        "cp",
    ],
    "solver_source": [
        "external",
        "internal",
    ],
}

# Known primitive names. Extend this list when adding benchmarks for new ciphers.
# Values must match the string used in the "primitive" field of benchmark JSONs.
PRIMITIVES = [
    "AES",
    "AES-128",
    "AES-192",
    "AES-256",
    "Ascon",
    "Gimli",
    "PRESENT",
    "Speck-8/16",
    "Speck-32/64",
    "Speck-64/128",
    "SIMON-32/64",
    "SIMON-64/128",
]

RESULT_STATUSES = ["sat", "unsat", "optimum", "timeout", "error", "unknown", "skipped"]


def allowed_values(field: str) -> list[str]:
    return list(TAXONOMY[field])
