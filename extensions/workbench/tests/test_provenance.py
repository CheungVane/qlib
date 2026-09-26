import copy,json,unittest
from pathlib import Path
from quant_workbench.provenance import classify,capabilities_audit


class ProvenanceTests(unittest.TestCase):
    def setUp(self):self.package=json.loads((Path(__file__).parents[1]/'examples/generic-result.json').read_text())

    def test_fixture_wins_over_native_metric_name(self):
        audit=classify(self.package,'qlib_mlflow_v1')
        self.assertEqual(audit['run']['kind'],'fixture')
        self.assertTrue(all(x['provenance']['kind']=='fixture' for x in self.package['series']))

    def test_native_name_is_not_evidence(self):
        self.package['evidence']={}
        self.assertEqual(classify(self.package,'generic_json_v1')['run']['kind'],'unknown')
        self.assertEqual(self.package['series'][0]['provenance']['kind'],'unknown')

    def test_original_derived_and_custom_are_distinct(self):
        self.package['evidence']={'mlflow_run_id':'local-id','research_quality':{'status':'passed_checks'}}
        self.package['series'].append({**copy.deepcopy(self.package['series'][0]),'metric_id':'platform.drawdown'})
        result=classify(self.package,'qlib_mlflow_v1')
        self.assertEqual(self.package['series'][0]['provenance']['kind'],'native')
        self.assertEqual(self.package['series'][-1]['provenance']['kind'],'derived')
        quality=next(x for x in result['fields'] if '有效IC' in x['field'])
        self.assertEqual(quality['kind'],'custom')
        self.assertEqual(result['data_nature'],'synthetic')

    def test_missing_not_zero_and_capability_limits(self):
        self.package['evidence']={'mlflow_run_id':'local-id'}
        self.package['series'][0]['points']=[{'x':'2021-07-01','value':None,'reason':'missing'}]
        classify(self.package,'qlib_mlflow_v1')
        self.assertEqual(self.package['series'][0]['provenance']['availability'],'missing')
        self.assertTrue(any(x['kind']=='unsupported' for x in capabilities_audit()))
