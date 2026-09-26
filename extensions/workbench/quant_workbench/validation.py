"""Validation statistics: purged folds, uniqueness weights, PSR/DSR and PBO.

Contract: docs/spec/VALIDATION.md. Everything is platform-computed and must carry its
formula, parameters, sample basis and limitations; small samples fail closed.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist
from typing import Any

from . import numeric
from .dto import json_safe

MAX_COMBINATIONS = 5000


class ValidationError(ValueError):
    """Invalid validation input; the API maps this to 400 with the reason preserved."""


def _numpy():
    return numeric.numpy(ValidationError, "validation needs numpy (install the 'analysis' extra)")


# -- data leakage -------------------------------------------------------------
def purged_folds(n_samples: int, spans=None, n_splits: int = 5, embargo: int = 0) -> dict[str, Any]:
    """Contiguous test folds whose training set excludes overlapping labels (AFML ch.7)."""
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 10:
        raise ValidationError("purged folds need at least 10 samples")
    if isinstance(n_splits, bool) or not isinstance(n_splits, int) or not 2 <= n_splits <= 20:
        raise ValidationError("n_splits must be between 2 and 20")
    if isinstance(embargo, bool) or not isinstance(embargo, int) or embargo < 0:
        raise ValidationError("embargo must be a non-negative integer")
    if n_samples // n_splits < 2:
        raise ValidationError("not enough samples per fold")
    spans = spans or [(index, index) for index in range(n_samples)]
    if len(spans) != n_samples:
        raise ValidationError("spans must cover every sample")
    bounds = [(int(start), int(end)) for start, end in spans]

    def overlaps(start: int, end: int, low: int, high: int) -> bool:
        return start <= high and end >= low

    folds = []
    size = n_samples / n_splits
    for fold in range(n_splits):
        low = int(round(fold * size))
        high = int(round((fold + 1) * size)) - 1
        if high < low:
            continue
        test = list(range(low, high + 1))
        train, purged = [], 0
        for index, (start, end) in enumerate(bounds):
            if low <= index <= high:
                continue
            if overlaps(start, end, low, high):
                purged += 1
                continue
            if high < index <= high + embargo:
                purged += 1
                continue
            train.append(index)
        folds.append({"fold": fold, "test_start": low, "test_end": high,
                      "test_count": len(test), "train_count": len(train), "purged": purged,
                      "purged_ratio": purged / n_samples, "test": test, "train": train})
    return {"n_samples": n_samples, "n_splits": len(folds), "embargo": embargo, "folds": folds,
            "formula": "test folds are contiguous blocks; training drops labels overlapping the "
                       "test window and the following `embargo` samples"}


def uniqueness_weights(spans) -> dict[str, Any]:
    """Average uniqueness per sample (AFML 4.1) from label spans."""
    spans = [(int(start), int(end)) for start, end in spans]
    if not spans:
        raise ValidationError("spans are required")
    if any(end < start for start, end in spans):
        raise ValidationError("span end must not precede span start")
    horizon = max(end for _, end in spans) + 1
    concurrency = [0] * max(horizon, 1)
    for start, end in spans:
        for position in range(start, end + 1):
            if 0 <= position < len(concurrency):
                concurrency[position] += 1
    weights = []
    for start, end in spans:
        values = [1.0 / concurrency[position] for position in range(start, end + 1)
                  if concurrency[position]]
        weights.append(sum(values) / len(values) if values else 0.0)
    total = sum(weights)
    return {"samples": len(weights), "effective_samples": total,
            "mean_weight": total / len(weights), "min_weight": min(weights),
            "max_weight": max(weights), "concurrency_peak": max(concurrency) if concurrency else 0,
            "formula": "weight_i = mean_t(1 / concurrency_t) over the label span of sample i"}


# -- Sharpe inference ---------------------------------------------------------
def _sharpe(returns) -> float:
    value = numeric.sharpe(returns)
    if value is None:
        raise ValidationError("returns have zero variance or fewer than two observations")
    return value


def probabilistic_sharpe(returns, benchmark: float = 0.0) -> dict[str, Any]:
    """PSR: probability that the true Sharpe exceeds `benchmark` (Bailey & López de Prado)."""
    np = _numpy()
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    count = len(values)
    if count < 10:
        raise ValidationError("probabilistic Sharpe needs at least 10 observations")
    sharpe = _sharpe(values)
    centred = values - values.mean()
    std = values.std(ddof=1)
    skew = float((centred ** 3).mean() / std ** 3)
    kurtosis = float((centred ** 4).mean() / std ** 4)
    variance = 1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2
    if variance <= 0:
        raise ValidationError("invalid Sharpe variance for PSR")
    z_score = (sharpe - benchmark) * math.sqrt(count - 1) / math.sqrt(variance)
    return {"sharpe": sharpe, "observations": count, "skew": skew, "kurtosis": kurtosis,
            "benchmark": benchmark, "psr": NormalDist().cdf(z_score), "z_score": z_score}


def deflated_sharpe(returns, trial_sharpes, benchmark: float | None = None) -> dict[str, Any]:
    """DSR: PSR against the expected maximum Sharpe of `N` trials (selection bias corrected)."""
    np = _numpy()
    trials = [float(value) for value in trial_sharpes if value is not None]
    if len(trials) < 2:
        raise ValidationError("deflated Sharpe needs at least two trial Sharpes")
    base = probabilistic_sharpe(returns)
    spread = float(np.std(trials, ddof=1))
    if spread == 0:
        raise ValidationError("trial Sharpes have zero variance; expected maximum is undefined")
    count = len(trials)
    gamma = 0.5772156649015329
    normal = NormalDist()
    expected_max = spread * ((1 - gamma) * normal.inv_cdf(1 - 1 / count)
                             + gamma * normal.inv_cdf(1 - 1 / (count * math.e)))
    target = expected_max if benchmark is None else benchmark
    z_score = (base["sharpe"] - target) * math.sqrt(base["observations"] - 1) / math.sqrt(
        1 - base["skew"] * base["sharpe"] + ((base["kurtosis"] - 1) / 4) * base["sharpe"] ** 2)
    return {**base, "trials": count, "trial_sharpe_std": spread,
            "expected_max_sharpe": expected_max, "benchmark": target,
            "dsr": NormalDist().cdf(z_score), "dsr_z_score": z_score}


def pbo(returns_matrix, n_blocks: int = 8) -> dict[str, Any]:
    """CSCV probability of backtest overfitting across configurations."""
    np = _numpy()
    matrix = np.asarray(returns_matrix, dtype=float)
    if matrix.ndim != 2:
        raise ValidationError("returns matrix must be two dimensional (time × configurations)")
    rows, columns = matrix.shape
    if columns < 2:
        raise ValidationError("PBO needs at least two configurations")
    if isinstance(n_blocks, bool) or not isinstance(n_blocks, int) or n_blocks < 4 or n_blocks % 2:
        raise ValidationError("n_blocks must be an even integer of at least 4")
    if rows < n_blocks * 2:
        raise ValidationError("not enough observations for the requested blocks")
    if math.comb(n_blocks, n_blocks // 2) > MAX_COMBINATIONS:
        raise ValidationError("too many combinations; reduce n_blocks")
    if not np.isfinite(matrix).all():
        raise ValidationError("returns matrix contains non-finite values (align dates first)")
    edges = np.linspace(0, rows, n_blocks + 1).astype(int)
    blocks = [matrix[edges[index]:edges[index + 1]] for index in range(n_blocks)]
    seen, duplicates = {}, []
    for column in range(columns):
        key = tuple(np.round(matrix[:, column], 12).tolist())
        if key in seen:
            duplicates.append([seen[key], column])
        else:
            seen[key] = column

    def sharpe(block):
        std = block.std(axis=0, ddof=1)
        mean = block.mean(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = np.where(std > 0, mean / std, 0.0)
        # a zero-variance series is scored by its sign so a flat positive config is not punished
        return np.where(std > 0, ratio, np.where(mean > 0, np.inf, np.where(mean < 0, -np.inf, 0.0)))

    below = 0
    total = 0
    for chosen in combinations(range(n_blocks), n_blocks // 2):
        in_sample = np.vstack([blocks[index] for index in chosen])
        out_sample = np.vstack([blocks[index] for index in range(n_blocks) if index not in chosen])
        in_scores = sharpe(in_sample)
        best = int(np.argmax(in_scores))
        out_scores = sharpe(out_sample)
        finite = out_scores[np.isfinite(out_scores)]
        if finite.size < 2:
            continue
        rank = float((out_scores[best] > finite).sum() + 0.5 * (out_scores[best] == finite).sum())
        relative = rank / finite.size
        total += 1
        if relative <= 0.5:
            below += 1
    if not total:
        raise ValidationError("no usable CSCV split")
    return {"pbo": below / total, "splits": total, "blocks": n_blocks, "configurations": columns,
            "observations": rows, "duplicate_configurations": duplicates,
            "degenerate": bool(duplicates),
            "note": ("存在完全相同的配置（例如同情景重复运行）：PBO 不具区分意义，只说明这些配置不可区分"
                     if duplicates else None),
            "formula": "CSCV: in-sample best configuration ranked out-of-sample; PBO is the share "
                       "of splits where it lands at or below the out-of-sample median"}


def validation_report(configs: list[dict[str, Any]], *, horizon: int = 1, splits: int = 5,
                      embargo: int | None = None, trials: int | None = None,
                      blocks: int = 8) -> dict[str, Any]:
    """Compose the validation DTO: PSR/DSR per configuration, PBO across them, leakage summary."""
    np = _numpy()
    if not configs:
        raise ValidationError("at least one configuration is required")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 60:
        raise ValidationError("horizon must be between 1 and 60 trading days")
    embargo = horizon if embargo is None else embargo
    axis = None
    for config in configs:
        dates = list(config["dates"])
        axis = dates if axis is None else [day for day in axis if day in set(dates)]
    if not axis or len(axis) < 10:
        raise ValidationError("configurations do not share enough aligned observations")
    aligned = []
    for config in configs:
        lookup = dict(zip(config["dates"], config["returns"]))
        values = [lookup.get(day) for day in axis]
        if any(value is None for value in values):
            raise ValidationError(f"configuration {config.get('title') or config['run_id']} has gaps on the aligned axis")
        aligned.append(np.asarray(values, dtype=float))
    sharpes = [_sharpe(values) for values in aligned]
    rows = []
    for config, values, sharpe in zip(configs, aligned, sharpes):
        entry = {"run_id": config["run_id"], "title": config.get("title"), "observations": len(values),
                 "sharpe": sharpe, "return_source": config.get("return_source")}
        try:
            entry["psr"] = probabilistic_sharpe(values)
        except ValidationError as exc:
            entry["psr"] = {"available": False, "reason": str(exc)}
        try:
            declared = trials if trials else len(configs)
            if declared < 2:
                raise ValidationError("deflated Sharpe needs a declared trial count of at least two")
            entry["dsr"] = deflated_sharpe(values, sharpes, benchmark=None)
            entry["dsr"]["declared_trials"] = declared
            if declared != len(configs):
                entry["dsr"]["note"] = "trial count declared by the caller; spread uses the observed configurations"
        except ValidationError as exc:
            entry["dsr"] = {"available": False, "reason": str(exc)}
        rows.append(entry)
    not_available = []
    try:
        pbo_result = pbo(np.column_stack(aligned), blocks)
    except ValidationError as exc:
        pbo_result = {"available": False, "reason": str(exc)}
        not_available.append({"metric": "pbo", "reason": str(exc)})
    spans = [(index, min(index + horizon, len(axis) - 1)) for index in range(len(axis))]
    leakage = purged_folds(len(axis), spans, n_splits=splits, embargo=embargo)
    weights = uniqueness_weights(spans)
    not_available.append({"metric": "live_out_of_sample",
                          "reason": "尚无前瞻/实盘样本；DSR 与 PBO 都只能基于历史样本"})
    return json_safe({
        "basis": {
            "kind": "platform_validation",
            "formulas": {
                "psr": "PSR = Φ((SR - SR*)·√(n-1) / √(1 - γ3·SR + (γ4-1)/4·SR²))",
                "dsr": "SR* = σ(SR_trials)·((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)))，γ 为 Euler-Mascheroni",
                "pbo": "CSCV：IS 最优配置在 OOS 的分位 ≤ 中位的比例",
                "purge": "训练集剔除与测试窗口标签重叠的样本，并再剔除其后 embargo 个样本",
            },
            "parameters": {"horizon": horizon, "embargo": embargo, "splits": splits,
                           "blocks": blocks, "trials": trials or len(configs)},
            "sample": {"start": axis[0], "end": axis[-1], "observations": len(axis),
                       "configurations": len(configs)},
            "configs": [{"run_id": row["run_id"], "title": row["title"],
                         "dataset_version": (config.get("dataset") or {}).get("version")}
                        for row, config in zip(rows, configs)],
            "provenance": "平台计算（收益来自已记录结果；不是引擎原生指标）",
        },
        "configs": rows,
        "pbo": pbo_result,
        "leakage": {"purged_folds": leakage, "uniqueness": weights},
        "not_available": not_available,
        "limitations": [
            "PSR/DSR 假设收益近似独立同分布，重叠样本已通过唯一性权重披露但未直接改写显著性",
            "PBO 依赖配置集合：集合里没有真正的候选差异时，PBO 只反映这些配置的相对稳定性",
            "没有前瞻样本，历史 PBO 与 DSR 不能替代实盘验证",
        ],
    })
