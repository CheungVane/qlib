"""Registered factor input boundaries, independent labels and UI module delivery."""
from datetime import date, timedelta
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from quant_workbench import data_directory as dd
from quant_workbench.adapters.snapshot_files import seal_record
from quant_workbench.adapters.snapshot_analysis import SnapshotAnalysisDirectory, dataset_identity
from quant_workbench.adapters.baseline_factors import baseline_panels
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.domain.errors import SnapshotError
from quant_workbench.services.factors import FactorService


class SnapshotAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.days = [date(2025, 1, 1) + timedelta(days=i) for i in range(35)]
        self.symbols = [f'SH60000{i}' for i in range(6)]
        for folder in ('features', 'instruments', 'status', '_registry'):
            (self.root / folder).mkdir()
        (self.root / 'calendar.txt').write_text('\n'.join(map(str, self.days)))
        (self.root / 'instruments/csi500.txt').write_text(''.join(
            f'{symbol}\t{self.days[0]}\t{self.days[-1 if i else -3]}\n' for i, symbol in enumerate(self.symbols)))
        for i, symbol in enumerate(self.symbols):
            folder = self.root / 'features' / symbol.lower()
            folder.mkdir()
            close = [10 + i + t * (0.1 + i * 0.03) + math.sin(t + i) * 0.1 for t in range(35)]
            for field, values in {'close': close, 'high': [p+1 for p in close], 'low': [p-1 for p in close],
                                  'volume': [100]*35, 'factor': [1]*35, 'change': [1]*35}.items():
                (folder / f'{field}.day.bin').write_bytes(struct.pack('<36f', 0, *values))
            # Missing/blocked observation inside a future window must invalidate the label.
            (self.root / 'status' / f'{symbol}.csv').write_text('date,turn,tradestatus,isST\n' + ''.join(
                f'{d},0,1,{1 if i == 0 and t == 26 else 0}\n' for t, d in enumerate(self.days)))
        record = dd.build_snapshot_record(snapshot_id='test', source={'source_class': 'free_community_unverified'},
            components=[{'kind': kind, 'uri': uri, 'content_digest': 'pending', 'source_class': 'free_community_unverified'}
                        for kind, uri in [('calendar', 'calendar.txt'), ('bar', 'features'),
                                          ('universe', 'instruments'), ('status', 'status')]])
        self.record = seal_record(self.root, record, {'price_basis': 'finv_adjusted_v1', 'universe': 'csi500'}, {'passed': True})
        (self.root / '_registry/test.json').write_text(json.dumps(self.record))
        self.directory = SnapshotAnalysisDirectory(self.root / '_registry', self.root)
        self.dataset, self.calendar = dataset_identity(self.record)

    def test_identity_and_bytes_fail_closed(self):
        for dataset, calendar in [({**self.dataset, 'version': 'wrong'}, self.calendar),
                                  (self.dataset, 'wrong'), ({**self.dataset, 'id': 'snapshot:unknown'}, self.calendar)]:
            with self.assertRaises(SnapshotError):
                self.directory.resolve(dataset, calendar)
        (self.root / 'status/SH600000.csv').write_text('changed')
        source = self.directory.resolve(self.dataset, self.calendar)
        with self.assertRaises(SnapshotError):
            source.read(list(map(str, self.days)), self.symbols, (5,))

    def test_full_window_and_membership_and_zero_turn(self):
        source = self.directory.resolve(self.dataset, self.calendar)
        result = source.read(list(map(str, self.days)), self.symbols, (1, 5))
        self.assertTrue(math.isnan(result['labels'][5][24, 0]))  # ST at t+2, endpoints are valid
        self.assertTrue(math.isfinite(result['labels'][1][24, 0]))
        self.assertTrue(math.isnan(result['labels'][1][33, 0]))  # outside membership
        reader = dd.FreeSnapshotReader(self.root, self.record)
        panels = list(baseline_panels(reader, self.days[0], self.days[-1]))
        self.assertEqual(len(panels), 3)
        self.assertEqual(panels[0][1]['dates'], list(map(str, self.days[20:])))
        self.assertEqual(panels[2][1]['values'][1], 0.0)  # zero turnover is observed, not missing
        close = reader.bin_series(self.symbols[1], 'close')[1]
        self.assertAlmostEqual(result['labels'][1][24, 1], close[25]/close[24]-1)

    def test_real_service_never_uses_current_profile_and_import_is_idempotent(self):
        legacy = Mock(side_effect=AssertionError('real input must never use current profile'))
        service = FactorService(LocalResultRepository(self.root / 'store'), legacy, self.directory)
        ids = []
        for identity, panel in baseline_panels(dd.FreeSnapshotReader(self.root, self.record), self.days[0], self.days[-1]):
            first = service.import_factor_panel(identity, panel)
            again = service.import_factor_panel(identity, panel)
            self.assertEqual(first['panel_id'], again['panel_id'])
            self.assertFalse(again['panel_created'])
            ids.append(first['factor_id'])
        report = service.factor_analysis(ids, [1, 5], analysis_version=2)
        self.assertEqual(report['basis']['snapshot']['content_digest'], self.dataset['version'])
        self.assertEqual(report['basis']['sample']['dates'], 15)
        legacy.assert_not_called()
        service.market_data = None
        with self.assertRaises(SnapshotError):
            service.factor_analysis(ids, [1], analysis_version=2)
        legacy.assert_not_called()

    def test_frontend_module_graph_is_served(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        from quant_workbench.application import WorkbenchService
        client = TestClient(create_app(WorkbenchService(LocalResultRepository(self.root / 'store'))))
        self.assertIn('/ui/startup.js', client.get('/').text)
        for asset in ('startup.js', 'app.js', 'state.js', 'transport.js'):
            response = client.get('/ui/' + asset)
            self.assertEqual(response.status_code, 200)
            self.assertIn('javascript', response.headers['content-type'])
