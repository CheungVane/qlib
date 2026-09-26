import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_workbench.research import ResearchSnapshots, review_result
from quant_workbench.telemetry import RequestTelemetry
from quant_workbench.api import create_app
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository


class ResearchTests(unittest.TestCase):
    def test_snapshot_pagination_search_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);identity='a'*24
            row={'schema_version':1,'id':identity,'title':'Mom5 因子','updated_at':'2026-01-01','status':'incomplete'}
            (root/(identity+'.json')).write_text(json.dumps(row))
            snapshots=ResearchSnapshots(root)
            self.assertIsNone(snapshots.detail('../secret'))
            self.assertEqual(snapshots.listing(query='mom5')['total'],1)
            self.assertEqual(snapshots.listing(offset=1)['items'],[])
            (root/('b'*24+'.json')).symlink_to(root/(identity+'.json'))
            self.assertIsNone(snapshots.detail('b'*24))

    def test_missing_values_are_not_zero_and_checks_not_alpha(self):
        package={'run':{'synthetic':True,'dataset':{'version':None}},'series':[],
                 'evidence':{'research_quality':{'status':'passed_checks'}}}
        review=review_result(package)
        self.assertIsNone(review['facts']['ending_equity'])
        self.assertTrue(any('模拟' in x for x in review['gaps']))
        self.assertTrue(any('排名' in x for x in review['gaps']))
        self.assertIn('不足',review['conclusion'])

    def test_telemetry_window_and_denominator(self):
        with patch('quant_workbench.telemetry.time.time',return_value=1000):
            t=RequestTelemetry();self.assertIsNone(t.snapshot()['error_rate'])
            t.record(200,10);t.record(404,20);t.record(500,30)
            s=t.snapshot();self.assertAlmostEqual(s['error_rate'],1/3)
            self.assertEqual(s['client_errors'],1)
        with patch('quant_workbench.telemetry.time.time',return_value=1301):
            self.assertEqual(t.snapshot()['completed_requests'],0)

    def test_api_matches_service_and_handles_internal_errors(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=ResearchSnapshots(root/'research');store.root.mkdir()
            identity='c'*24
            (store.root/(identity+'.json')).write_text(json.dumps({'schema_version':1,'id':identity,'title':'测试','updated_at':'2026','events':[]}))
            service=WorkbenchService(LocalResultRepository(root/'db'),research=store)
            client=TestClient(create_app(service))
            self.assertEqual(client.get('/v1/research').json(),service.research_list())
            self.assertEqual(client.get('/v1/research/'+identity).json(),service.research_detail(identity))
            self.assertEqual(client.get('/v1/research/missing').status_code,404)
            with patch.object(service,'health',side_effect=RuntimeError('private failure')):
                r=client.get('/v1/health')
                self.assertEqual(r.status_code,500)
                self.assertNotIn('private failure',r.text)
            stats=client.get('/v1/observability').json()
            self.assertEqual(stats['completed_requests'],3)
            self.assertEqual(stats['client_errors'],1)

    def test_compare_rejects_unknown_scenario_and_different_windows(self):
        import copy
        from datetime import date,timedelta
        fixture=Path(__file__).parents[1]/'examples/generic-result.json'
        package=json.loads(fixture.read_text())
        package['run']['dataset']['version']='verified-test-fixture'
        with tempfile.TemporaryDirectory() as tmp:
            service=WorkbenchService(LocalResultRepository(Path(tmp)))
            a=service.import_package('test','a','v1',package)
            other=copy.deepcopy(package)
            for entry in other['series']:
                if entry['axis']=='trading_date':
                    for point in entry['points']:point['x']=(date.fromisoformat(point['x'])+timedelta(days=1)).isoformat()
            b=service.import_package('test','b','v1',other)
            comparison=service.compare([a['run_id'],b['run_id']],'platform.equity')
            self.assertFalse(comparison['ranking_allowed'])
            self.assertIn('date_window_differs',comparison['reasons'])
            self.assertIn('execution_scenario_unknown_or_differs',comparison['reasons'])
            self.assertEqual(comparison['revisions'][a['run_id']],a['revision_id'])
