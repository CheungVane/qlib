"""FD counterexamples: semantic errors must fail independently of replay determinism."""
import csv
from copy import deepcopy
from datetime import date
import importlib.util
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from quant_workbench import data_directory as dd, factor_pipeline as fp, factors
from quant_workbench.adapters.snapshot_files import seal_record, VerifiedFiles, record_digest
from quant_workbench.adapters.data_preparation import audit_bars
from quant_workbench.domain.data import decode_bin
from quant_workbench.domain.errors import SnapshotError
from quant_workbench.free_sources import parse_turnover_csv


def fixture(root):
    (root / 'features/sh600001').mkdir(parents=True)
    (root / 'instruments').mkdir()
    (root / 'status').mkdir()
    (root / 'calendar.txt').write_text('2025-01-02\n2025-01-03\n2025-01-06\n')
    # Overlapping membership must not duplicate keys. Disjoint ending membership stays out.
    (root / 'instruments/csi500.txt').write_text('SH600001\t2025-01-02\t2025-01-03\nSH600001\t2025-01-03\t2025-01-03\n')
    (root / 'instruments/all.txt').write_text('SH600001\t2025-01-02\t2025-01-06\n')
    (root / 'status/SH600001.csv').write_text('date,turn,tradestatus,isST\n2025-01-02,0,1,0\n2025-01-03,,1,0\n')
    for field, data in {'close': [0, 10, 12, 13], 'volume': [1, 100, 120], 'factor': [1, 2, 4]}.items():
        (root / f'features/sh600001/{field}.day.bin').write_bytes(struct.pack('<' + 'f'*len(data), *data))
    record = dd.build_snapshot_record(snapshot_id='test', source={'source_class': 'synthetic'}, components=[
        {'kind': kind, 'uri': uri, 'content_digest': 'pending', 'source_class': 'synthetic'}
        for kind, uri in [('calendar', 'calendar.txt'), ('bar', 'features'), ('universe', 'instruments'), ('status', 'status')]])
    return seal_record(root, record, {'price_basis': 'finv_adjusted_v1'}, {'passed': True})


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = fixture(self.root)

    def test_verified_bytes_cannot_drift_or_move_to_different_root(self):
        verified = VerifiedFiles(self.root, self.record)
        before = verified.read('status', 'SH600001.csv')
        import shutil
        with tempfile.TemporaryDirectory() as other:
            moved=Path(other)/'root'
            shutil.copytree(self.root,moved)
            self.assertEqual(VerifiedFiles(moved,self.record).read('status','SH600001.csv'),before)
            (moved/'status/SH600001.csv').write_bytes(before.replace(b',0,1,0',b',1,1,0'))
            with self.assertRaises(SnapshotError):
                VerifiedFiles(moved,self.record).read('status','SH600001.csv')
        path = self.root / 'status/SH600001.csv'
        path.write_bytes(before.replace(b',0,1,0', b',1,1,0'))
        self.assertEqual(verified.read('status', 'SH600001.csv'), before)  # immutable cached bytes
        with self.assertRaises(SnapshotError) as caught:
            VerifiedFiles(self.root, self.record).read('status', 'SH600001.csv')
        self.assertEqual(caught.exception.code, 'snapshot_content_mismatch')
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(SnapshotError):
                VerifiedFiles(Path(other), self.record).read('calendar')

    def test_unknown_draft_or_changed_interpretation_is_rejected(self):
        for change in ({'schema_version': 1}, {'status': 'draft'}, {'interpretation': {'price_basis': 'raw_with_factor_v1'}}):
            record = {**self.record, **change}
            with self.assertRaises(SnapshotError):
                VerifiedFiles(self.root, record)
        changed = deepcopy(self.record)
        changed['components'][0]['uri'] = '../escape'
        changed['content_digest'] = record_digest(changed)
        with self.assertRaises(SnapshotError):
            VerifiedFiles(self.root, changed)

    def test_materialization_deduplicates_members_and_aligns_each_field(self):
        reader = dd.FreeSnapshotReader(self.root, self.record)
        target = self.root / 'panel.csv'
        result = dd.materialize_panel(reader, output=target, universe='csi500', fields=['close', 'volume'],
                    start=date(2025,1,2), end=date(2025,1,6), limit=1)
        with target.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(result['rows'], 2)
        self.assertEqual([(r['date'], r['close'], r['volume']) for r in rows],
                         [('2025-01-02','10',''), ('2025-01-03','12','100')])
        self.assertEqual(len({(r['date'],r['symbol']) for r in rows}), 2)
        path = self.root / 'instruments/csi500.txt'
        path.write_text('SH600001\t2025-01-02\t2025-01-06\n')
        with self.assertRaises(SnapshotError):
            dd.materialize_panel(dd.FreeSnapshotReader(self.root,self.record), output=self.root/'other.csv',
                universe='csi500', fields=['close'],start=date(2025,1,2),end=date(2025,1,6))

    def test_price_semantics_and_factor_offsets(self):
        # Explicit FINV close ratio stays 20%; multiplying factor would invent 140%.
        dates=['2025-01-02','2025-01-03','2025-01-06']
        (self.root/'calendars').mkdir()
        (self.root/'calendars/day.txt').write_text('\n'.join(dates))
        adjusted=factors.load_close_series(self.root,dates,['SH600001'],price_basis='finv_adjusted_v1')['values'][:,0]
        raw=factors.load_close_series(self.root,dates,['SH600001'],price_basis='raw_with_factor_v1')['values'][:,0]
        self.assertAlmostEqual(adjusted[1]/adjusted[0]-1,.2)
        self.assertTrue(math.isnan(raw[0]))
        self.assertEqual(list(raw[1:]),[24,52])
        with self.assertRaises(factors.FactorError):
            factors.load_close_series(self.root,dates,['SH600001'])

    def test_membership_uses_join_exit_and_reentry_dates(self):
        (self.root/'instruments/csi500.txt').write_text(
            'SH600001\t2025-01-02\t2025-01-02\nSH600001\t2025-01-06\t2025-01-06\n'
            'SH600002\t2025-01-03\t2025-01-06\n')
        record=seal_record(self.root,self.record,{'price_basis':'finv_adjusted_v1'},{'passed':True})
        reader=dd.FreeSnapshotReader(self.root,record)
        symbols,days=fp.historical_membership(reader,reader.calendar(),'csi500')
        self.assertEqual(symbols,['SH600001','SH600002'])
        self.assertEqual(days,[{'SH600001'},{'SH600002'},{'SH600001','SH600002'}])
        reader.calendar()[0]=date(2000,1,1)
        reader.instruments('csi500')[0]['symbol']='MUTATED'
        self.assertEqual(reader.calendar()[0],date(2025,1,2))
        self.assertEqual(fp.historical_membership(reader,reader.calendar(),'csi500')[1],days)

    def test_bad_headers_and_bad_cache_are_rejected_zero_is_preserved(self):
        for data in (struct.pack('<ff',.5,1), struct.pack('<ff',3,1), b'x'):
            with self.assertRaises(ValueError):
                decode_bin(data,3)
        prefix='date,turn,tradestatus,isST\n'
        for tail in ('','2025-01-02,0,1,0\n2025-01-02,1,1,0\n','2025-01-02,nan,1,0\n','2025-01-02,1,2,0\n'):
            with self.assertRaises(ValueError):
                parse_turnover_csv(prefix+tail)
        self.assertEqual(parse_turnover_csv(prefix+'2025-01-02,0,1,0')['2025-01-02']['turn'],0)

    def test_label_purge_and_missing_calendar_ic(self):
        self.assertEqual(fp.label_tradability([True,False,True],2),[False]*3)
        prices=[10+i/100 for i in range(160)]
        before=fp.forward_return(prices,10)
        prices[120:]=[999]*40
        after=fp.forward_return(prices,10)
        window=fp.label_window(slice(0,120),10)
        self.assertEqual(before[window],after[window])
        self.assertNotEqual(before[110],after[110])
        values=[math.sin(i)+.2 for i in range(60)]
        self.assertIsNotNone(fp.newey_west_t(values,4))
        values[30]=None
        self.assertIsNone(fp.newey_west_t(values,4))
        self.assertEqual(fp.research_stats(values,5,20)['significance_reason'],'missing_trading_day_ic')

    def test_publisher_does_not_trust_a_passing_flag(self):
        # Fixture has no required OHLC/benchmark files despite its caller-supplied flag.
        registry=self.root/'registry'
        with self.assertRaises((SnapshotError,ValueError)):
            dd.publish_snapshot(registry,self.record,data_root=self.root)
        self.assertFalse((registry/'test.json').exists())


class CacheCompletionTests(unittest.TestCase):
    def test_incomplete_query_and_legacy_cache_are_not_success(self):
        script=Path(__file__).resolve().parents[3]/'scripts/fetch_csi500_turnover.py'
        spec=importlib.util.spec_from_file_location('fetch_for_test',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Result:
            error_code='0';error_msg=''; count=0
            def next(self):
                self.count+=1
                if self.count==1:return True
                self.error_code='9';self.error_msg='truncated';return False
            def get_row_data(self):return ['2025-01-02','1','1','0']
        class Source:
            def query_history_k_data_plus(self,*a,**kw):return Result()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            _,status=module._write_symbol(Source(),'SH600001','sh.600001','2025-01-01','2025-01-31',root)
            self.assertTrue(status.startswith('error:9'))
            self.assertEqual(list(root.iterdir()),[])
            (root/'SH600001.csv').write_text('date,turn,tradestatus,isST\n')
            _,status=module._write_symbol(None,'SH600001','sh.600001','2025-01-01','2025-01-31',root)
            self.assertIn('unverified_cache',status)

    def test_completed_cache_is_reusable_only_for_same_request(self):
        script=Path(__file__).resolve().parents[3]/'scripts/fetch_csi500_turnover.py'
        spec=importlib.util.spec_from_file_location('fetch_success_test',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Result:
            error_code='0';error_msg='';count=0
            def next(self):self.count+=1;return self.count==1
            def get_row_data(self):return ['2025-01-02','0','1','0']
        class Source:
            def query_history_k_data_plus(self,*a,**kw):return Result()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            args=('SH600001','sh.600001','2025-01-01','2025-01-31',root)
            self.assertEqual(module._write_symbol(Source(),*args)[1],'ok:1')
            meta=json.loads((root/'SH600001.meta.json').read_text())
            self.assertEqual(meta['returned_coverage'],{'start':'2025-01-02','end':'2025-01-02'})
            self.assertEqual(module._write_symbol(None,*args)[1],'skipped')
            self.assertIn('unverified_cache',module._write_symbol(None,*args[:3],'2025-02-28',root)[1])


class PreparationIntegrationTests(unittest.TestCase):
    def test_negative_price_leaves_report_but_never_publishes(self):
        import hashlib
        import tarfile
        from quant_workbench import free_sources as fs
        from quant_workbench.adapters.data_preparation import prepare
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'free_cn_20260924'
            (source/'calendars').mkdir(parents=True)
            (source/'calendars/day.txt').write_text('2025-01-02\n2025-01-03\n')
            (source/'instruments').mkdir()
            for name in ('all','csi500'):
                (source/f'instruments/{name}.txt').write_text('SH600001\t2025-01-02\t2025-01-03\n')
            for symbol in ('SH600001','SH000905'):
                path=source/'features'/symbol.lower();path.mkdir(parents=True)
                for field in fs.ARCHIVE_FIELDS:
                    values=[-1,1] if symbol=='SH600001' and field=='close' else [1,1]
                    (path/f'{field}.day.bin').write_bytes(struct.pack('<fff',0,*values))
            cache=root/'free_cn_20260924_enrichment/turnover';cache.mkdir(parents=True)
            (cache/'SH600001.csv').write_text('date,turn,tradestatus,isST\n2025-01-02,1,1,0\n2025-01-03,1,1,0\n')
            archive=root/'_downloads/test/qlib_bin.tar.gz';archive.parent.mkdir(parents=True)
            with tarfile.open(archive,'w:gz') as handle:handle.add(source,arcname='qlib_bin')
            manifest=archive.with_name('qlib_bin.manifest.json')
            manifest.write_text(json.dumps({'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                'archive_size_bytes':archive.stat().st_size,'target_trade_date':'2025-01-03'}))
            record=dd.build_snapshot_record(snapshot_id='free_cn_20260924',source={'release_tag':'test'},
                components=[{'kind':kind,'uri':uri,'source_class':'synthetic','content_digest':'old'}
                            for kind,uri in [('calendar','free_cn_20260924/calendars/day.txt'),('bar','free_cn_20260924/features'),
                                             ('universe','free_cn_20260924/instruments/all.txt'),('status','free_cn_20260924_enrichment/turnover')]],
                provenance={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                            'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()})
            dd.publish_snapshot(root/'_registry',record)
            result=prepare(root, snapshot_id="free_cn_20260924_v2")
            self.assertFalse(result['published'])
            self.assertFalse(result['quality']['passed'])
            self.assertFalse((root/'_registry/free_cn_20260924_v2.json').exists())
            self.assertTrue((root/'processed/free_cn_20260924_v2/preparation-report.json').exists())

            # A second valid source must still not publish if materialization fails.
            from unittest.mock import patch
            (source/'features/sh600001/close.day.bin').write_bytes(struct.pack('<fff',0,1,1))
            with tarfile.open(archive,'w:gz') as handle:handle.add(source,arcname='qlib_bin')
            manifest.write_text(json.dumps({'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                'archive_size_bytes':archive.stat().st_size,'target_trade_date':'2025-01-03'}))
            record['provenance'].update(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                       manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
            (root/'_registry/free_cn_20260924.json').write_text(json.dumps(record))
            with patch('quant_workbench.adapters.data_preparation.normalized_panels', side_effect=ValueError('replay failure')):
                with self.assertRaisesRegex(ValueError,'replay failure'):
                    prepare(root,snapshot_id='failed_replay')
            self.assertFalse((root/'_registry/failed_replay.json').exists())
            # Positive control exercises the same complete production pipeline.
            completed=prepare(root,snapshot_id='complete')
            self.assertTrue(completed['published'])
            self.assertEqual(completed['normalized_panels']['rows'],2)
            self.assertTrue((root/'_registry/complete.json').exists())
