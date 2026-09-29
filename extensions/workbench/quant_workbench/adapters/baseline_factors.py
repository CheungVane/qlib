"""Deterministic research baselines computed only from a verified real snapshot."""
import math
from datetime import date
from .. import factor_pipeline as fp
from .snapshot_analysis import dataset_identity

FORMULAS = {
    'momentum_20': 'close[t] / close[t-20] - 1; finite endpoints required',
    'volatility_20': 'sample standard deviation of 20 daily close returns; all 21 closes required',
    'turnover_20': 'mean of 20 observed turnover percentages, including t; missing remains null',
}


def baseline_panels(reader, start: date, end: date):
    reader.require_verified()
    if (reader.record['interpretation'].get('price_basis') != 'finv_adjusted_v1'
            or reader.record['source'].get('source_class') != 'free_community_unverified'):
        raise ValueError('baseline panels require finv_adjusted_v1')
    days = [d for d in reader.calendar() if start <= d <= end]
    if len(days) <= 20:
        raise ValueError('baseline window requires more than 20 calendar observations')
    symbols, members = fp.historical_membership(reader, days, 'csi500')
    if len(symbols) * (len(days) - 20) > 400000:
        raise ValueError('baseline window exceeds panel cell budget')
    values = {name: {} for name in FORMULAS}
    for symbol in symbols:
        status = reader.turnover(symbol)
        loaded = fp.load_symbol_series(reader, symbol, days, status)
        flags = fp.tradable(loaded, days, status)
        computed = {'momentum_20': fp.momentum(loaded['close'], 20),
                    'volatility_20': fp.volatility(loaded['close'], 20),
                    'turnover_20': fp.mean_of(loaded['turn'], 20)}
        for name, column in computed.items():
            values[name][symbol] = [v if flags[i] and symbol in members[i] and math.isfinite(v) else None
                                    for i, v in enumerate(column)]
    dataset, calendar = dataset_identity(reader.record)
    for name, formula in FORMULAS.items():
        identity = {'source_instance_id': 'workbench-real-baselines',
                    'external_id': f'{dataset["id"]}:{start}:{end}:{name}:v1', 'name': name,
                    'dataset': dataset, 'calendar_id': calendar,
                    'definition': {'formulation': formula, 'computation_version': 'real-baseline-v1',
                                   'warmup_rows': 20, 'universe': 'historical csi500 membership on factor date'},
                    'provenance': {'market_data_kind': 'real', 'origin': 'platform_computed',
                                   'source_class': reader.record['source']['source_class'],
                                   'historical_available_at': 'unknown'}}
        yield identity, {'schema_version': 1, 'name': name, 'calendar_id': calendar,
                         'dates': [d.isoformat() for d in days[20:]], 'instruments': symbols,
                         'values': [values[name][symbol][i] for i in range(20, len(days)) for symbol in symbols]}
