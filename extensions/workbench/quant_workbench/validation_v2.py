"""Validation analysis version 2: PSR/DSR/PBO under the frozen T02-D contract.

Contract: docs/spec/VALIDATION.md §2A. Defects fixed relative to v1 (§2A.7):

* the declared trial count N actually enters the expected-maximum-Sharpe formula;
* CSCV rank is omega = r/(K+1) with the candidate itself excluded;
* equal-length blocks with the earliest remainder dropped and disclosed;
* duplicate configurations are collapsed; zero-dispersion and non-finite inputs fail
  closed instead of being scored with infinity/zero hacks or filtered away.

Everything is platform-computed; DSR/PBO stay exploratory while the trial scope is
incomplete, and none of this certifies alpha.
"""

from __future__ import annotations

import itertools
import math
import statistics
from datetime import datetime, timezone
from statistics import NormalDist

from . import validation as validation_layer

EULER_GAMMA = 0.5772156649015329
ZERO_TOLERANCE = 1e-12
MIN_OBSERVATIONS = 10
SCHEMA_VERSION = 2

DEFINITIONS = {
    "psr": {
        "formula": "PSR = Phi((SR - SR*) * sqrt(n-1) / sqrt(1 - g3*SR + (g4-1)/4*SR^2))",
        "sharpe": "mean/std(ddof=1), per period, not annualised",
        "moments": "population moments over ddof=1 standard deviation (denominator n)",
        "kurtosis": "non-excess (normal = 3)",
        "benchmark_default": 0.0,
    },
    "dsr": {
        "formula": "SR* = sigma(SR_trials)*((1-g)*Phi^-1(1-1/N) + g*Phi^-1(1-1/(N*e)))",
        "declared_n": "N enters the formula; sigma uses the usable configurations (ddof=1)",
        "correlation_assumption": "unmodeled_iid",
        "scope": "exploratory unless the trial scope is complete",
    },
    "pbo": {
        "algorithm": "CSCV: out-of-sample rank of the in-sample best configuration",
        "rank": "omega = r/(K+1), r from 1 with the candidate excluded",
        "blocks": "equal-length blocks; the earliest T mod S observations are dropped",
        "ties": "identical configurations are collapsed before ranking",
    },
}


def probabilistic_sharpe(values, benchmark: float = 0.0) -> dict:
    """PSR with fail-closed inputs (missing observations are never filtered away)."""
    series = [float(value) for value in values]
    if any(not math.isfinite(value) for value in series):
        return {"availability": "unavailable", "reason": "missing_or_nonfinite_observation"}
    count = len(series)
    if count < MIN_OBSERVATIONS:
        return {"availability": "unavailable", "reason": "insufficient_observations"}
    average = statistics.fmean(series)
    spread = statistics.stdev(series)
    if spread <= ZERO_TOLERANCE:
        return {"availability": "unavailable", "reason": "zero_dispersion"}
    sharpe = average / spread
    skew = sum((value - average) ** 3 for value in series) / count / spread ** 3
    kurtosis = sum((value - average) ** 4 for value in series) / count / spread ** 4
    variance_term = 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2
    if variance_term <= 0:
        return {"availability": "unavailable", "reason": "invalid_sharpe_variance"}
    z_score = (sharpe - benchmark) * math.sqrt(count - 1) / math.sqrt(variance_term)
    return {
        "availability": "available", "value": NormalDist().cdf(z_score), "reason": None,
        "inputs": {"observations": count, "mean": average, "std_ddof1": spread,
                   "sharpe_per_period": sharpe, "skew": skew, "kurtosis": kurtosis,
                   "variance_term": variance_term, "benchmark": benchmark, "z_score": z_score},
    }


def expected_max_sharpe(trial_sharpes, declared_trials: int) -> float:
    """E[max SR] with the declared N entering the quantile terms (§2A.6)."""
    if declared_trials < 2:
        raise ValueError("declared trials must be at least two")
    trials = [float(value) for value in trial_sharpes
              if value is not None and math.isfinite(value)]
    if len(trials) < 2:
        raise ValueError("needs at least two usable trial Sharpes")
    spread = statistics.stdev(trials)
    if spread <= ZERO_TOLERANCE:
        raise ValueError("trial Sharpes have zero dispersion")
    normal = NormalDist()
    return spread * ((1 - EULER_GAMMA) * normal.inv_cdf(1 - 1 / declared_trials)
                     + EULER_GAMMA * normal.inv_cdf(1 - 1 / (declared_trials * math.e)))


def deflated_sharpe(values, trial_sharpes, declared_trials: int) -> dict:
    """DSR = PSR against the expected maximum Sharpe of the declared N trials."""
    usable = [value for value in trial_sharpes if value is not None and math.isfinite(value)]
    if len(usable) < 2:
        return {"availability": "unavailable",
                "reason": "deflated_sharpe_needs_at_least_two_trials"}
    if declared_trials < 2:
        return {"availability": "unavailable", "reason": "declared_trials_below_two"}
    try:
        benchmark = expected_max_sharpe(usable, declared_trials)
    except ValueError as error:
        return {"availability": "unavailable", "reason": "insufficient_trial_dispersion",
                "detail": str(error)}
    base = probabilistic_sharpe(values)
    if base["availability"] != "available":
        return {"availability": "unavailable", "reason": base["reason"]}
    inputs = base["inputs"]
    z_score = ((inputs["sharpe_per_period"] - benchmark)
               * math.sqrt(inputs["observations"] - 1) / math.sqrt(inputs["variance_term"]))
    return {
        "availability": "available", "value": NormalDist().cdf(z_score), "reason": None,
        "inputs": {**inputs, "expected_max_sharpe": benchmark,
                   "declared_trials": declared_trials, "usable_trials": len(usable),
                   "trial_sharpe_std_ddof1": statistics.stdev(usable), "z_score": z_score},
    }


def collapse_duplicates(matrix) -> tuple[list, list]:
    """Collapse identical configuration columns (1e-12) and report the collapses."""
    columns = [tuple(round(float(value), 12) for value in column) for column in zip(*matrix)]
    seen: dict[tuple, int] = {}
    kept, collapsed = [], []
    for index, column in enumerate(columns):
        if column in seen:
            collapsed.append({"kept_index": seen[column], "dropped_index": index})
            continue
        seen[column] = index
        kept.append(index)
    return kept, collapsed


def _sharpe(column) -> float | None:
    if any(not math.isfinite(value) for value in column):
        return None
    spread = statistics.stdev(column)
    if spread <= ZERO_TOLERANCE:
        return None
    return statistics.fmean(column) / spread


def cscv_pbo(matrix, blocks: int = 8) -> dict:
    """CSCV probability of backtest overfitting under the frozen §2A.7 rules."""
    rows = [list(map(float, row)) for row in matrix]
    observations = len(rows)
    if not rows:
        return {"availability": "unavailable", "reason": "no_observations"}
    kept, collapsed = collapse_duplicates(rows)
    if len(kept) < 2:
        return {"availability": "unavailable", "reason": "degenerate_configurations",
                "collapsed_duplicates": collapsed, "configurations": len(kept)}
    if blocks < 4 or blocks % 2:
        return {"availability": "unavailable", "reason": "blocks_must_be_even_and_at_least_four"}
    if observations < blocks * 2:
        return {"availability": "unavailable", "reason": "not_enough_observations_for_blocks"}
    remainder = observations % blocks
    usable = rows[remainder:]
    size = len(usable) // blocks
    columns = [[row[column] for row in usable] for column in kept]
    combinations_total = math.comb(blocks, blocks // 2)
    counted = 0
    for chosen in itertools.combinations(range(blocks), blocks // 2):
        out = [index for index in range(blocks) if index not in chosen]
        in_sample = [_sharpe([value for block in chosen
                              for value in columns[column][block * size:(block + 1) * size]])
                     for column in range(len(kept))]
        out_sample = [_sharpe([value for block in out
                               for value in columns[column][block * size:(block + 1) * size]])
                      for column in range(len(kept))]
        if any(value is None for value in in_sample + out_sample):
            return {"availability": "unavailable", "reason": "zero_dispersion_block",
                    "collapsed_duplicates": collapsed, "blocks": blocks}
        best = max(range(len(kept)), key=lambda index: (in_sample[index], -index))
        below = sum(1 for index, value in enumerate(out_sample)
                    if index != best and value < out_sample[best])
        tied = sum(1 for index, value in enumerate(out_sample)
                   if index != best and value == out_sample[best])
        omega = (1 + below + 0.5 * tied) / (len(kept) + 1)
        if omega <= 0.5:
            counted += 1
    return {
        "availability": "available", "value": counted / combinations_total, "reason": None,
        "blocks": blocks, "observations_per_block": size,
        "dropped_observations": {"count": remainder, "policy": "drop_earliest",
                                 "note": "kept the most recent complete window"},
        "configurations": len(kept), "combinations_total": combinations_total,
        "combinations_used": combinations_total, "collapsed_duplicates": collapsed,
    }


def build_report(configs: list[dict], *, horizon: int = 1, splits: int = 5,
                 embargo: int | None = None, blocks: int = 8,
                 trials: int | None = None) -> dict:
    """Compose the v2 DTO from return views already resolved by the caller."""
    excluded: list[dict] = []
    usable: list[dict] = []
    for config in configs:
        if config.get("reason"):
            excluded.append({"run_id": config["run_id"], "reason": config["reason"]})
            continue
        series = [float(value) for value in config.get("values") or []]
        if any(not math.isfinite(value) for value in series):
            excluded.append({"run_id": config["run_id"],
                             "reason": "missing_or_nonfinite_observation"})
            continue
        usable.append({**config, "values": series})

    axis = None
    for config in usable:
        dates = list(config["dates"])
        axis = dates if axis is None else [day for day in axis if day in set(dates)]
    axis = axis or []
    aligned, kept_configs = [], []
    for config in usable:
        lookup = dict(zip(config["dates"], config["values"]))
        values = [lookup.get(day) for day in axis]
        if any(value is None for value in values):
            excluded.append({"run_id": config["run_id"],
                             "reason": "not_aligned_with_request_axis"})
            continue
        kept_configs.append(config)
        aligned.append([float(value) for value in values])

    inputs = [{"run_id": item["run_id"], "revision_id": item.get("revision_id"),
               "resolution": item.get("resolution", "latest_at_request")} for item in configs]
    if not kept_configs or len(axis) < MIN_OBSERVATIONS:
        reason = ("insufficient_common_observations" if kept_configs
                  else "no_usable_configurations")
        return {
            "schema_version": SCHEMA_VERSION, "analysis_version": 2, "inputs": inputs,
            "basis": {"window": {"policy": "intersection_of_requested_revisions",
                                 "start": axis[0] if axis else None,
                                 "end": axis[-1] if axis else None,
                                 "observations": len(axis)},
                      "trial_scope": {"available_configurations": len(configs),
                                      "usable_configurations": len(kept_configs),
                                      "excluded": excluded}},
            "configs": [], "pbo": {"availability": "unavailable", "reason": reason},
            "definitions": DEFINITIONS,
            "not_available": [{"metric": "psr_dsr_pbo", "reason": reason}],
            "limitations": [f"v2 needs at least {MIN_OBSERVATIONS} common observations"],
        }

    trial_sharpes, configs_out = [], []
    for config, values in zip(kept_configs, aligned):
        psr = probabilistic_sharpe(values)
        sharpe = (psr.get("inputs") or {}).get("sharpe_per_period")
        if sharpe is not None:
            trial_sharpes.append(sharpe)
        configs_out.append({"run_id": config["run_id"], "title": config.get("title"),
                            "revision_id": config.get("revision_id"),
                            "observations": len(values), "sharpe_per_period": sharpe,
                            "psr": psr})

    declared = trials if trials is not None else len(kept_configs)
    below_usable = declared < len(kept_configs)
    for (config, values), entry in zip(zip(kept_configs, aligned), configs_out):
        if below_usable:
            entry["dsr"] = {"availability": "unavailable",
                            "reason": "declared_trials_below_usable_configurations"}
        else:
            entry["dsr"] = deflated_sharpe(values, trial_sharpes, declared)

    if len(kept_configs) >= 2:
        pbo = cscv_pbo([list(column) for column in zip(*aligned)], blocks)
    else:
        pbo = {"availability": "unavailable",
               "reason": "pbo_needs_at_least_two_configurations"}

    spans = [(index, min(index + horizon, len(axis) - 1)) for index in range(len(axis))]
    effective_embargo = horizon if embargo is None else embargo
    uniqueness = validation_layer.uniqueness_weights(spans)
    leakage = {
        "purged_folds": validation_layer.purged_folds(len(axis), spans, n_splits=splits,
                                                      embargo=effective_embargo),
        "uniqueness": {"samples": uniqueness["samples"],
                       "weight_sum": uniqueness["effective_samples"],
                       "mean_weight": uniqueness["mean_weight"],
                       "min_weight": uniqueness["min_weight"],
                       "max_weight": uniqueness["max_weight"],
                       "concurrency_peak": uniqueness["concurrency_peak"],
                       "note": "weight_sum (sum of uniqueness weights) is not an independent "
                               "effective sample size and must not be reported as one"},
    }

    return {
        "schema_version": SCHEMA_VERSION, "analysis_version": 2, "inputs": inputs,
        "basis": {
            "kind": "platform_validation",
            "window": {"policy": "intersection_of_requested_revisions",
                       "start": axis[0], "end": axis[-1], "observations": len(axis)},
            "sharpe": {"estimator": "mean_over_std_ddof1", "ddof": 1,
                       "moments": "population_moments_over_ddof1_std",
                       "kurtosis": "non_excess", "frequency": "per_period",
                       "annualisation": {"applied": False}},
            "parameters": {"horizon": horizon, "splits": splits, "embargo": embargo,
                           "blocks": blocks},
            "trial_scope": {
                "available_configurations": len(configs),
                "usable_configurations": len(kept_configs), "excluded": excluded,
                "declared_n": declared,
                "declared_n_source": ("declared_by_caller" if trials is not None
                                      else "inferred_from_request_selection"),
                "correlation_assumption": "unmodeled_iid", "scope_completeness": "incomplete"},
        },
        "configs": configs_out, "pbo": pbo, "definitions": DEFINITIONS,
        "leakage": leakage,
        "resolved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "not_available": [], "limitations": [
            "试验范围不完整时，DSR 与 PBO 只能作为探索性诊断",
            "没有前瞻样本；历史诊断不能替代前瞻或实盘证据",
            "horizon/splits/embargo 只影响泄漏摘要，不进入 PSR/DSR/PBO 的数值",
            "共同观测取各 revision 的日期交集；被排除的配置在 trial_scope.excluded 中列出原因",
        ],
    }
