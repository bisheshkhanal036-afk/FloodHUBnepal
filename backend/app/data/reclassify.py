"""Generic reclassification engine: continuous or categorical values -> 5
discrete risk classes, driven entirely by a criterion's
`reclassification_rules` (schemas/criterion.schema.json) — never
hardcoded per criterion, so literature-sourced thresholds can be updated
without touching this code.

Each rule is {"min", "max", "min_inclusive", "max_inclusive", "risk_class"}
— see schemas/criterion.schema.json's reclassificationRule definition.
`min`/`max` of None mean unbounded below/above; a categorical single-value
rule sets min == max with both bounds inclusive.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from .aoi import AOI
from .cache import cached_or_compute
from .errors import ReclassificationError

# Output sentinel for "no risk class assigned" pixels (nodata input, or —
# should it ever happen — a value the configured rules don't cover).
# risk classes themselves are 1-5, so 0 is unambiguous as "not classified".
RECLASSIFIED_NODATA = 0


def _rule_bounds(rule: dict) -> tuple[float, float, bool, bool]:
    lo = -math.inf if rule.get("min") is None else float(rule["min"])
    hi = math.inf if rule.get("max") is None else float(rule["max"])
    lo_inclusive = rule.get("min_inclusive", True)
    hi_inclusive = rule.get("max_inclusive", False)
    return lo, hi, lo_inclusive, hi_inclusive


def validate_reclassification_rules(rules: list[dict]) -> list[dict]:
    """Sort `rules` by lower bound and check they don't overlap.

    A *range* rule set (every rule spans min < max, e.g. slope-in-degrees
    thresholds) must also be gap-free: it describes a continuous domain,
    so every value in that domain needs a rule to land in, per the
    coverage requirement documented on schemas/criterion.schema.json's
    reclassificationRule.

    A *categorical* rule set (any rule has min == max — a single discrete
    source code, e.g. a land-cover class) is exempt from the gap check:
    it enumerates specific valid codes, not a continuum, so the "gaps"
    between e.g. class code 10 and class code 50 are simply values that
    will never occur, not missing coverage. apply_reclassification's own
    runtime check (raise on a value that matched no rule) is what catches
    a genuinely unexpected code for this case, in place of static
    contiguity.

    Returns the sorted list (does not mutate the input).
    """
    if not rules:
        raise ReclassificationError("reclassification_rules is empty")

    ordered = sorted(rules, key=lambda r: _rule_bounds(r)[0])
    is_categorical = any(_rule_bounds(r)[0] == _rule_bounds(r)[1] for r in ordered)

    for i in range(len(ordered) - 1):
        cur, nxt = ordered[i], ordered[i + 1]
        _, cur_hi, _, cur_hi_incl = _rule_bounds(cur)
        nxt_lo, _, nxt_lo_incl, _ = _rule_bounds(nxt)

        if cur_hi > nxt_lo or (cur_hi == nxt_lo and cur_hi_incl and nxt_lo_incl):
            raise ReclassificationError(
                f"overlap in reclassification_rules between {cur!r} and {nxt!r}"
            )
        if not is_categorical and cur_hi < nxt_lo:
            raise ReclassificationError(
                f"gap in reclassification_rules between {cur!r} and {nxt!r}: "
                f"no rule covers ({cur_hi}, {nxt_lo})"
            )

    return ordered


def apply_reclassification(
    values: np.ndarray,
    rules: list[dict],
    input_nodata: float | None,
    output_dtype=np.uint8,
) -> np.ndarray:
    """Map `values` to risk classes 1-5 using `rules`. Input pixels equal
    to `input_nodata` map to RECLASSIFIED_NODATA (0) without being tested
    against any rule. Any *valid* pixel that still doesn't match any rule
    raises ReclassificationError rather than silently leaving it
    unclassified (SPEC.md, Nodata handling: "raise a clear error rather
    than silently producing corrupted output" — the same principle
    applies here to reclassification coverage gaps).
    """
    ordered = validate_reclassification_rules(rules)

    if input_nodata is None:
        valid_mask = np.ones(values.shape, dtype=bool)
    elif isinstance(input_nodata, float) and math.isnan(input_nodata):
        valid_mask = ~np.isnan(values)
    else:
        valid_mask = values != input_nodata

    output = np.full(values.shape, RECLASSIFIED_NODATA, dtype=output_dtype)
    matched = np.zeros(values.shape, dtype=bool)

    for rule in ordered:
        lo, hi, lo_incl, hi_incl = _rule_bounds(rule)
        cond = (values >= lo) if lo_incl else (values > lo)
        cond &= (values <= hi) if hi_incl else (values < hi)
        cond &= valid_mask
        output[cond] = rule["risk_class"]
        matched |= cond

    unmatched = valid_mask & ~matched
    if np.any(unmatched):
        example = float(values[unmatched].flat[0])
        raise ReclassificationError(
            f"{int(unmatched.sum())} pixel(s) matched no reclassification rule "
            f"(example out-of-range value: {example}); rules must cover the full "
            "domain of valid input values"
        )

    return output


def rules_fingerprint(rules: list[dict]) -> str:
    """A short, stable hash of `rules`, independent of key/list ordering
    — two rule lists that are semantically identical (same rules, listed
    in a different order, or with default-valued keys omitted vs.
    explicit) fingerprint identically; any actual change to a threshold,
    a risk_class, or the rule set's shape fingerprints differently.

    Used as the cache-versioning key for cached reclassified output (see
    apply_reclassification_cached): a criterion's reclassification_rules
    are expected to change over time as literature-sourced thresholds are
    updated, and a cache entry keyed only by AOI would otherwise keep
    serving a stale result computed under the old thresholds.
    """
    normalized = [
        {
            "min": r.get("min"),
            "max": r.get("max"),
            "min_inclusive": r.get("min_inclusive", True),
            "max_inclusive": r.get("max_inclusive", False),
            "risk_class": r["risk_class"],
        }
        for r in sorted(rules, key=lambda r: _rule_bounds(r))
    ]
    payload = json.dumps(normalized, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def apply_reclassification_cached(
    source_name: str,
    aoi: AOI,
    values: np.ndarray,
    rules: list[dict],
    input_nodata: float | None,
    output_dtype=np.uint8,
) -> np.ndarray:
    """Same as apply_reclassification, but cached per (source_name, AOI,
    rules) via cache.cached_or_compute — the rules' fingerprint is folded
    into the cache key (as `version`) precisely so that changing
    reclassification_rules invalidates any stale cached result for the
    same AOI, rather than silently reusing it.
    """
    version = rules_fingerprint(rules)
    return cached_or_compute(
        f"reclassified_{source_name}",
        aoi,
        lambda: apply_reclassification(values, rules, input_nodata, output_dtype),
        version=version,
    )
