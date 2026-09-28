"""A40 structure gate; does not close execution/data/research acceptance gaps."""
import ast
import inspect
from pathlib import Path
import unittest

from architecture_rules import violations
from quant_workbench import ports
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.domain.workflows import WorkflowKind, WorkflowPlan, WorkflowStep, workflow_plan

ROOT = Path(__file__).resolve().parents[1] / 'quant_workbench'


class ArchitectureTests(unittest.TestCase):
    def test_repository_dependency_boundaries(self):
        failures = []
        for path in sorted(ROOT.rglob('*.py')):
            module = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
            failures.extend(f'{module}: {v}' for v in violations(module, path.read_text()))
        self.assertEqual([], failures)

    def test_checker_rejects_wrong_directions_and_hidden_io(self):
        cases = [('domain.bad', 'import sqlite3'),
                 ('domain.bad', 'from ..services.results import ResultService'),
                 ('services.bad', 'from ..adapters.storage.storage import LocalResultRepository'),
                 ('services.bad', 'from .. import storage'),
                 ('adapters.bad', 'from ..execution import ExecutionService'),
                 ('api', 'import sqlite3'),
                 ('application', 'from .adapters.executors import QlibCNExecutor'),
                 ('new_manager', 'pass'),
                 ('domain.bad', "__import__('subprocess')"),
                 ('domain.bad', "path.read_text()"),
                 ('storage', 'class DuplicateRepository: pass')]
        for module, source in cases:
            with self.subTest(module=module, source=source):
                self.assertTrue(violations(module, source))
        self.assertFalse(violations('services.new_use_case', 'from ..ports import ResultRepository'))

    def test_repository_ports_cover_actual_service_calls(self):
        for module, protocol in [('results', ports.ResultRepository), ('factors', ports.FactorRepository),
                                 ('execution', ports.AttemptRepository), ('attention', ports.AttemptRepository)]:
            tree = ast.parse((ROOT / 'services' / f'{module}.py').read_text())
            used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                    and ast.unparse(n.value) == 'self.repository'}
            self.assertFalse(used - set(dir(protocol)), (module, used - set(dir(protocol))))
        for protocol in (ports.ResultRepository, ports.FactorRepository, ports.AttemptRepository):
            for name, method in protocol.__dict__.items():
                if name.startswith('_') or not callable(method):
                    continue
                actual = getattr(LocalResultRepository, name)
                self.assertEqual(inspect.signature(method), inspect.signature(actual), name)

    def test_compatibility_exports_are_identical(self):
        from quant_workbench.storage import LocalResultRepository as old_repository
        from quant_workbench.execution import ExecutionService as old_execution
        from quant_workbench.services.execution import ExecutionService
        from quant_workbench.research_lifecycle import ExperimentDefinitionRevision
        from quant_workbench.domain.research import ExperimentDefinitionRevision as canonical_run
        self.assertIs(old_repository, LocalResultRepository)
        self.assertIs(old_execution, ExecutionService)
        self.assertIs(ExperimentDefinitionRevision, canonical_run)

    def test_fixed_plans_keep_training_out_of_backtest(self):
        self.assertEqual(['prepare', 'signal', 'portfolio', 'simulate', 'evaluate'],
                         [s.key for s in workflow_plan('backtest').steps])
        self.assertEqual(['prepare', 'train', 'predict', 'evaluate'],
                         [s.key for s in workflow_plan('train').steps])
        self.assertEqual(['prepare', 'generate', 'evaluate'],
                         [s.key for s in workflow_plan('mine').steps])
        with self.assertRaises(ValueError):
            workflow_plan('live')
        for steps in [(), (WorkflowStep('x', 'owner', ('later',)),),
                      (WorkflowStep('x', 'owner'), WorkflowStep('x', 'owner'))]:
            with self.assertRaises(ValueError):
                WorkflowPlan(WorkflowKind.TRAIN, steps)

    def test_explicit_composition_uses_isolated_settings_without_starting_engines(self):
        import tempfile
        from unittest.mock import patch
        from quant_workbench.bootstrap import WorkbenchSettings, build_workbench
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict('os.environ', {'QWB_DATA_ROOT': '/unused-data-root',
                                           'QWB_RDAGENT_ROOT': '/unused-agent-root'}):
                service = build_workbench(WorkbenchSettings(root / 'store', root / 'data'),
                                          with_executors=False)
            self.assertIsNone(service.execution_service)
            self.assertIsNone(service.rdagent)
            self.assertEqual([], service.list_runs()['items'])
            self.assertEqual(False, service.data_snapshots()['available'])
            self.assertTrue((root / 'store').is_dir())
