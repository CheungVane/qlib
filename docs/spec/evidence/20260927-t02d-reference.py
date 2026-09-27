#!/usr/bin/env python3
"""T02-D 独立参考值复算（设计门证据，2026-09-27）。

按 docs/spec/VALIDATION.md §2A 冻结的定义重算 PSR/DSR/PBO 参考值。
本脚本不导入 extensions/workbench，只使用 Python 标准库：它证明 spec 登记的数字
可由定义独立算出，不证明工作台实现已经正确，也不构成功能验收。

用法：python3 docs/spec/evidence/20260927-t02d-reference.py
"""

from __future__ import annotations

import itertools
import math
import sys
from statistics import NormalDist, mean, stdev

EULER_GAMMA = 0.5772156649015329
ZERO_TOLERANCE = 1e-12
TOL = 1e-9
NORMAL = NormalDist()


def check(label, actual, expected, tol=TOL):
    if isinstance(expected, float):
        ok = abs(actual - expected) <= tol
    else:
        ok = actual == expected
    if not ok:
        print(f"[FAIL] {label}: actual={actual!r} expected={expected!r}", file=sys.stderr)
        raise SystemExit(1)
    print(f"[ok] {label}: {actual!r}")


def per_period_sharpe(values):
    """逐期 SR = mean/std(ddof=1)；零离散度返回 None（fail-closed）。"""
    if len(values) < 2:
        return None
    spread = stdev(values)
    if spread <= ZERO_TOLERANCE:
        return None
    return mean(values) / spread


def moments(values):
    """均值/标准差(ddof=1)/偏度/峰度(非超额)：矩的分母为 n，标准差为 ddof=1。"""
    count = len(values)
    average = mean(values)
    spread = stdev(values)
    centred = [value - average for value in values]
    return {
        "n": count,
        "mean": average,
        "sd": spread,
        "sharpe": average / spread,
        "skew": (sum(value ** 3 for value in centred) / count) / spread ** 3,
        "kurtosis": (sum(value ** 4 for value in centred) / count) / spread ** 4,
    }


def probabilistic_sharpe(values, benchmark=0.0):
    stats = moments(values)
    variance_term = (1 - stats["skew"] * stats["sharpe"]
                     + ((stats["kurtosis"] - 1) / 4) * stats["sharpe"] ** 2)
    z_score = ((stats["sharpe"] - benchmark) * math.sqrt(stats["n"] - 1)
               / math.sqrt(variance_term))
    return {**stats, "variance_term": variance_term, "z": z_score, "psr": NORMAL.cdf(z_score)}


def expected_max_sharpe(trial_sharpes, declared_trials):
    spread = stdev(trial_sharpes)
    return spread * ((1 - EULER_GAMMA) * NORMAL.inv_cdf(1 - 1 / declared_trials)
                     + EULER_GAMMA * NORMAL.inv_cdf(1 - 1 / (declared_trials * math.e)))


def deflated_sharpe(values, trial_sharpes, declared_trials):
    stats = probabilistic_sharpe(values)
    benchmark = expected_max_sharpe(trial_sharpes, declared_trials)
    z_score = ((stats["sharpe"] - benchmark) * math.sqrt(stats["n"] - 1)
               / math.sqrt(stats["variance_term"]))
    return {"expected_max_sharpe": benchmark, "z": z_score, "dsr": NORMAL.cdf(z_score)}


def cscv(blocks):
    """CSCV：ω = 秩/(N+1)，秩从 1 计且不含候选自身。"""
    n_blocks = len(blocks)
    n_configs = len(blocks[0])
    total = math.comb(n_blocks, n_blocks // 2)
    rows, counted = [], 0
    for chosen in itertools.combinations(range(n_blocks), n_blocks // 2):
        out = [index for index in range(n_blocks) if index not in chosen]
        in_sample = [per_period_sharpe([value for block in chosen for value in blocks[block][column]])
                     for column in range(n_configs)]
        out_sample = [per_period_sharpe([value for block in out for value in blocks[block][column]])
                      for column in range(n_configs)]
        if any(value is None for value in in_sample + out_sample):
            raise ValueError("zero dispersion inside a CSCV combination")
        best = max(range(n_configs), key=lambda index: (in_sample[index], -index))
        below = sum(1 for index, value in enumerate(out_sample)
                    if index != best and value < out_sample[best])
        tied = sum(1 for index, value in enumerate(out_sample)
                   if index != best and value == out_sample[best])
        rank = 1 + below + 0.5 * tied
        omega = rank / (n_configs + 1)
        counted += omega <= 0.5
        rows.append({"is_blocks": chosen, "oos_blocks": tuple(out),
                     "is_sharpe": [round(value, 6) for value in in_sample],
                     "oos_sharpe": [round(value, 6) for value in out_sample],
                     "best": best, "rank": rank, "omega": round(omega, 6),
                     "counted": omega <= 0.5})
    return {"pbo": counted / total, "combinations_total": total, "rows": rows}


def fixture_a():
    drifts = (0.001, 0.002, 0.003, 0.004)
    series = [[drift + (0.01 if index % 2 == 0 else -0.01) for index in range(20)]
              for drift in drifts]
    return drifts, series


def main():
    print("== 夹具 A：4 配置 × 20 个交易日（PSR / DSR） ==")
    drifts, series = fixture_a()
    psr_expected = (0.6645459833, 0.8023651500, 0.8990026123, 0.9556755846)
    sharpe_expected = (0.0974679434, 0.1949358869, 0.2924038303, 0.3898717738)
    for index, (drift, values) in enumerate(zip(drifts, series), start=1):
        stats = probabilistic_sharpe(values)
        print(f"C{index}: drift={drift} mean={stats['mean']:.6f} sd={stats['sd']:.10f} "
              f"SR={stats['sharpe']:.10f} skew={stats['skew']:.0f} "
              f"kurtosis={stats['kurtosis']:.4f} z={stats['z']:.10f} PSR={stats['psr']:.10f}")
        check(f"C{index} SR", round(stats["sharpe"], 10), sharpe_expected[index - 1])
        check(f"C{index} PSR", round(stats["psr"], 10), psr_expected[index - 1])
    check("C2 峰度(非超额)", moments(series[1])["kurtosis"], 0.9025, tol=1e-12)

    trial_sharpes = [probabilistic_sharpe(values)["sharpe"] for values in series]
    dispersion = stdev(trial_sharpes)
    check("试验 SR 离散度 ddof=1", round(dispersion, 10), 0.1258305739)

    print("== DSR：候选=C2，只改变声明 N ==")
    dsr_expected = {4: (0.1323892188, 0.2727609572, 0.6074815132),
                    10: (0.1981326080, -0.0139406418, 0.4944386687),
                    20: (0.2391671724, -0.1928890559, 0.4235229281)}
    previous = None
    for declared in (4, 10, 20):
        result = deflated_sharpe(series[1], trial_sharpes, declared)
        print(f"N={declared}: expected_max={result['expected_max_sharpe']:.10f} "
              f"z={result['z']:.10f} DSR={result['dsr']:.10f}")
        expected_max, expected_z, expected_dsr = dsr_expected[declared]
        check(f"N={declared} expected_max", round(result["expected_max_sharpe"], 10), expected_max)
        check(f"N={declared} z", round(result["z"], 10), expected_z)
        check(f"N={declared} DSR", round(result["dsr"], 10), expected_dsr)
        if previous is not None:
            assert result["expected_max_sharpe"] > previous[0], "expected max must grow with N"
            assert result["dsr"] < previous[1], "DSR must fall as the benchmark grows"
            assert 0.0 < result["dsr"] < 1.0, "reference DSR must not saturate"
        previous = (result["expected_max_sharpe"], result["dsr"])

    print("== 夹具 B：PBO 主导（A 全块优于 B） ==")
    dominant = [[0.02, 0.04], [0.03, 0.05], [0.01, 0.03], [0.02, 0.06]]
    mirror = [[-value for value in block] for block in dominant]
    result_b = cscv([[dominant[index], mirror[index]] for index in range(4)])
    check("夹具 B PBO", round(result_b["pbo"], 6), 0.0)
    for row in result_b["rows"]:
        print("   ", row)

    print("== 夹具 C：PBO 中间值（2/6） ==")
    fixture_a_blocks = [[0.04, 0.06], [0.05, 0.07], [-0.05, -0.03], [-0.04, -0.02]]
    fixture_b_blocks = [[-0.04, -0.02], [-0.06, -0.04], [0.02, 0.04], [0.02, 0.04]]
    result_c = cscv([[fixture_a_blocks[index], fixture_b_blocks[index]] for index in range(4)])
    check("夹具 C PBO", round(result_c["pbo"], 6), round(1 / 3, 6))
    check("夹具 C 组合数", result_c["combinations_total"], 6)
    for row in result_c["rows"]:
        print("   ", row)

    print("== 夹具 D：重复配置必须折叠后不可用，而不是 PBO=1 ==")
    duplicate = [[0.02, 0.04], [0.03, 0.05], [0.01, 0.03], [0.02, 0.06]]
    collapsed = [duplicate]  # 两列完全相同，按 1e-12 容差折叠为一个代表
    check("夹具 D 折叠后配置数", len(collapsed), 1)

    print("\n所有 T02-D 参考值复算一致。")


if __name__ == "__main__":
    main()
