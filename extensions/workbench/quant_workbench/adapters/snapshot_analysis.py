"""Registered real-data analysis. Every consumed file is verified before parsing."""
from datetime import date
from pathlib import Path
import math

from .. import data_directory as dd, factor_pipeline as fp
from ..domain.errors import SnapshotError


def dataset_identity(record):
    identity = record['snapshot_id']
    calendar = next(c for c in record['components'] if c['kind'] == 'calendar')
    return ({'id': 'snapshot:' + identity, 'version': record['content_digest'], 'snapshot_label': identity},
            'calendar:' + calendar['content_digest'])


class SnapshotAnalysisDirectory:
    def __init__(self, registry: Path, root: Path):
        self.registry, self.root = Path(registry), Path(root)

    def resolve(self, dataset: dict, calendar_id: str):
        identity = dataset.get('id', '')
        if not identity.startswith('snapshot:'):
            raise ValueError('registered analysis requires a snapshot dataset identity')
        snapshot_id = identity.removeprefix('snapshot:')
        record = dd.load_snapshot(self.registry, snapshot_id)
        expected, expected_calendar = dataset_identity(record)
        if dataset.get('version') != expected['version'] or calendar_id != expected_calendar:
            raise SnapshotError('snapshot_content_mismatch', snapshot_id, 'dataset/calendar identity')
        reader = dd.FreeSnapshotReader(self.root, record)
        reader.require_verified()
        if (record['interpretation'].get('price_basis') != 'finv_adjusted_v1'
                or record['source'].get('source_class') != 'free_community_unverified'):
            raise SnapshotError('snapshot_unverified', snapshot_id, 'price_basis')
        return SnapshotAnalysisInput(reader)


class SnapshotAnalysisInput:
    def __init__(self, reader):
        self.reader = reader

    def calendar(self):
        return [d.isoformat() for d in self.reader.calendar()]

    def read(self, dates, instruments, horizons):
        import numpy as np
        days = [date.fromisoformat(d) for d in dates]
        universe = self.reader.record['interpretation'].get('universe', 'csi500')
        _, members = fp.historical_membership(self.reader, days, universe)
        eligible = [[symbol in group for symbol in instruments] for group in members]
        labels = {h: np.full((len(days), len(instruments)), np.nan) for h in horizons}
        for column, symbol in enumerate(instruments):
            if not any(symbol in group for group in members):
                continue
            series = {field: fp.aligned_series(self.reader, symbol, field, days)
                      for field in ('close', 'high', 'low')}
            status = self.reader.turnover(symbol)
            flags = fp.tradable(series, days, status)
            for row in range(len(days)):
                eligible[row][column] = eligible[row][column] and flags[row]
            for h in horizons:
                mask = fp.label_tradability(flags, h)
                values = fp.forward_return(series['close'], h)
                for row, value in enumerate(values):
                    if symbol in members[row] and mask[row] and math.isfinite(value):
                        labels[h][row, column] = value
        record = self.reader.record
        return {'labels': labels, 'membership': [v for row in eligible for v in row],
                'basis': {'label': record['snapshot_id'], 'content_digest': record['content_digest'],
                          'files': sum(len(c['files']) for c in record['components']),
                          'verification_scope': 'consumed file bytes', 'price_fields': 'close (already adjusted)',
                          'price_basis': 'finv_adjusted_v1', 'market_data_kind': 'real',
                          'source_class': record['source']['source_class'], 'historical_available_at': 'unknown',
                          'universe': universe, 'label_mask': 'whole-window observed prices/status, non-ST, non-flat'},
                'limitations': ['真实免费社区数据，非官方认证；历史available_at与源修订未知',
                                '仅预测标签；全窗口状态过滤与单价日排除是研究近似，不证明可成交',
                                '本页因子统计不是模型训练或组合回测结果']}
