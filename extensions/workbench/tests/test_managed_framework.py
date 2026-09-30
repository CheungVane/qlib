"""U31 structural contracts, using isolated doubles, never production stores/jobs.

These tests check orchestration and refusal, NOT SQL atomicity or engine support.
"""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from quant_workbench.domain.admission import (
    AdmissionCommand, AdmissionReceipt, AdmissionRequest, EntryPoint, PreparedAdmission)
from quant_workbench.domain.artifacts import ArtifactRef
from quant_workbench.domain.errors import ManagedExecutionUnavailable
from quant_workbench.domain.workflows import WorkflowKind, WorkflowPlan, WorkflowStep, workflow_plan
from quant_workbench.services.execution import ExecutionService
from quant_workbench.services.research_runs import ResearchRunService
from quant_workbench.services.data_pipeline import DataPipelineService
from quant_workbench.services.research_workflows import ResearchWorkflowService


def ref(kind, identifier=None, digit='a'):
    return ArtifactRef(identifier or kind, kind, 1, 'sha256:' + digit * 64)


class ManagedFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.policy = ref('execution_policy')
        self.definition = ref('research_definition')
        self.command = AdmissionCommand(EntryPoint.RESEARCH, self.definition, self.policy, 'key')
        self.prepared = PreparedAdmission(WorkflowKind.TRAIN, 'experiment', self.definition)
        self.receipt = AdmissionReceipt('run', 'attempt', 1, self.definition, None, self.policy, True)
        self.transaction = Mock()
        self.preflight = Mock()
        self.transaction.replay.side_effect = lambda command: self.events.append('replay')
        self.preflight.prepare_admission.side_effect = lambda command: self.events.append('preflight') or self.prepared
        self.transaction.admit_run.side_effect = lambda request: self.events.append('commit') or self.receipt
        self.service = ExecutionService(Mock(), executors=[], policy=object(),
                                        managed_admission=self.transaction, managed_preflight=self.preflight)

    def test_single_admission_boundary_and_no_legacy_start(self):
        self.service.submit = Mock(side_effect=AssertionError('legacy submit'))
        result = ResearchRunService(self.service).start(self.command)
        self.assertEqual(['replay', 'preflight', 'commit'], self.events)
        self.assertIs(self.receipt, result)
        request = self.transaction.admit_run.call_args.args[0]
        self.assertEqual(self.command, request.command)
        self.assertEqual(workflow_plan('train'), request.plan)
        self.service.submit.assert_not_called()

    def test_replay_before_expired_plan_or_unavailable_engine_check(self):
        previous = replace(self.receipt, created=False)
        self.transaction.replay.side_effect = lambda command: previous
        self.preflight.prepare_admission.side_effect = AssertionError('expired plan rechecked')
        self.assertIs(previous, self.service.admit_managed(self.command))
        self.assertTrue(previous.replayed)
        self.preflight.prepare_admission.assert_not_called()
        self.transaction.admit_run.assert_not_called()

    def test_conflict_preflight_and_transaction_failure_never_fall_through(self):
        for failure_point in ('replay', 'prepare_admission', 'admit_run'):
            with self.subTest(point=failure_point):
                self.setUp()
                target = self.preflight if failure_point == 'prepare_admission' else self.transaction
                getattr(target, failure_point).side_effect = RuntimeError(failure_point)
                with self.assertRaisesRegex(RuntimeError, failure_point):
                    self.service.admit_managed(self.command)
                if failure_point != 'admit_run':
                    self.transaction.admit_run.assert_not_called()

    def test_concurrent_winner_is_returned_from_atomic_boundary(self):
        previous = replace(self.receipt, created=False)
        self.transaction.admit_run.side_effect = lambda request: previous
        self.assertIs(previous, self.service.admit_managed(self.command))
        self.transaction.admit_run.assert_called_once()

    def test_preflight_cannot_replace_requested_revision(self):
        self.prepared = replace(self.prepared, definition_ref=ref('research_definition', digit='b'))
        with self.assertRaisesRegex(ValueError, 'substituted'):
            self.service.admit_managed(self.command)
        self.transaction.admit_run.assert_not_called()

    def test_data_and_human_entries_share_run_and_execution_owners(self):
        runs = ResearchRunService(self.service)
        data = DataPipelineService(runs)
        human = ResearchWorkflowService(runs)
        data_ref, plan = ref('data_definition'), ref('data_plan')
        self.prepared = PreparedAdmission(WorkflowKind.DATA_PREPARE, None, data_ref, plan)
        self.receipt = replace(self.receipt, definition_ref=data_ref, plan_ref=plan)
        data.start(plan, self.policy, 'data-key')
        req = self.transaction.admit_run.call_args.args[0]
        self.assertEqual('POST /v1/data-pipeline-runs', req.command.operation)
        self.assertEqual(['preflight', 'acquire', 'normalize', 'reconcile', 'validate', 'publish', 'report'],
                         [s.key for s in req.plan.steps])
        workflow = ref('research_workflow')
        self.receipt = replace(self.receipt, definition_ref=self.definition, plan_ref=None)
        self.prepared = PreparedAdmission(WorkflowKind.DIRECTION_REVIEW, 'experiment', self.definition,
                                          workflow_ref=workflow)
        human.start('workflow-entity', workflow, self.policy, 'human-key')
        req = self.transaction.admit_run.call_args.args[0]
        self.assertEqual('POST /v1/research-workflows/workflow-entity/start', req.command.operation)
        self.assertEqual(WorkflowKind.DIRECTION_REVIEW, req.plan.kind)
        self.assertIs(data.runs, human.runs)

    def test_human_workflow_cannot_implicitly_admit_training(self):
        workflow = ref('research_workflow')
        self.prepared = replace(self.prepared, workflow_ref=workflow)
        with self.assertRaisesRegex(ValueError, 'automatically train'):
            ResearchWorkflowService(ResearchRunService(self.service)).start(
                'workflow-entity', workflow, self.policy, 'human-key')
        self.transaction.admit_run.assert_not_called()

    def test_missing_or_partial_dependencies_fail_closed(self):
        execution = ExecutionService(Mock(), policy=object())
        with self.assertRaises(ManagedExecutionUnavailable):
            execution.admit_managed(self.command)
        with self.assertRaises(ManagedExecutionUnavailable):
            ResearchRunService(None).start(self.command)
        with self.assertRaises(ValueError):
            ExecutionService(Mock(), policy=object(), managed_admission=self.transaction)

    def test_reference_and_command_identity_are_strict_and_immutable(self):
        for changes in ({'schema_version': True}, {'schema_version': 0},
                        {'artifact_id': '../secret'}, {'content_digest': 'latest'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.definition, **changes)
        with self.assertRaises(ValueError):
            replace(self.command, reference=ref('data_plan'))
        for key in ('', 'k\n', 'x'*129):
            with self.assertRaises(ValueError):
                replace(self.command, idempotency_key=key)
        self.assertEqual(self.command.payload_digest(), replace(self.command, idempotency_key='another').payload_digest())
        self.assertNotEqual(self.command.payload_digest(), replace(
            self.command, reference=ref('research_definition', digit='b')).payload_digest())
        retry = AdmissionCommand(EntryPoint.RETRY, self.definition, self.policy, 'retry', run_id='run')
        self.assertEqual('POST /v1/research-runs/run/retry', retry.operation)

    def test_fixed_plans_cannot_smuggle_a_training_step_into_backtest(self):
        prepared = replace(self.prepared, kind=WorkflowKind.BACKTEST)
        forged = WorkflowPlan(WorkflowKind.BACKTEST, (WorkflowStep('train', 'training_adapter'),))
        with self.assertRaises(ValueError):
            AdmissionRequest(self.command, prepared, forged)
        for kind in WorkflowKind:
            plan = workflow_plan(kind)
            self.assertEqual(len(plan.steps), len({s.key for s in plan.steps}))
            if kind != WorkflowKind.TRAIN:
                self.assertNotIn('train', [s.key for s in plan.steps])

    def test_disabled_production_composition_has_no_fake_new_capabilities(self):
        import tempfile
        from pathlib import Path
        from quant_workbench.bootstrap import WorkbenchSettings, build_workbench
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            service = build_workbench(WorkbenchSettings(base/'store', base/'data'), with_executors=False)
            self.assertIs(service.research_runs, service.data_pipeline.runs)
            self.assertIs(service.research_runs, service.research_workflows.runs)
            with self.assertRaises(ManagedExecutionUnavailable):
                service.data_pipeline.start(ref('data_plan'), self.policy, 'disabled')
            self.assertEqual([], service.list_runs()['items'])
            with self.assertRaises(ValueError):
                build_workbench(WorkbenchSettings(base/'other', base/'data'), managed_admission=self.transaction)
            self.assertFalse((base/'other').exists())

    def test_bad_receipt_or_retry_run_is_not_reported_as_success(self):
        self.receipt = replace(self.receipt, execution_policy_ref=ref('execution_policy', digit='b'))
        with self.assertRaisesRegex(ValueError, 'receipt substituted'):
            self.service.admit_managed(self.command)
        receipt = replace(self.receipt, execution_policy_ref=self.policy)
        retry = AdmissionCommand(EntryPoint.RETRY, self.definition, self.policy, 'retry', run_id='other-run')
        with self.assertRaisesRegex(ValueError, 'different Run'):
            receipt.validate_command(retry)

    def test_worker_context_requires_utc_deadline_and_frozen_budget_scopes(self):
        from quant_workbench.domain.worker import ExecutionContext
        context = ExecutionContext('run', 'attempt', 'launch', self.definition, self.policy,
                                   None, ('global:policy1',), '2026-09-30T00:00:00.000Z', 'cancel', 'output')
        for changes in ({'budget_scope_ids': []}, {'budget_scope_ids': ()},
                        {'deadline_at': '2026-09-30'}, {'deadline_at': '2026-02-30T00:00:00.000Z'},
                        {'output_namespace': '/tmp/output'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(context, **changes)

    def test_source_chunks_and_compile_results_cannot_fake_validity(self):
        from quant_workbench.domain.data_pipeline import SourceFetchPlan
        from quant_workbench.domain.factor_expression import CompileDiagnostic, CompileReport
        from quant_workbench.domain.worker import ProducedArtifact
        produced = ProducedArtifact(ref('factor_definition'), 'sha256:' + 'b' * 64)
        source = SourceFetchPlan(ref('data_plan'), 'source', ref('capability_record'), ('chunk1',))
        with self.assertRaises(ValueError):
            replace(source, chunk_keys=('chunk1', 'chunk1'))
        with self.assertRaises(ValueError):
            replace(source, data_plan_ref=ref('dataset_snapshot'))
        diagnostic = CompileDiagnostic('future_offset', 'Future data cannot be a feature.')
        self.assertFalse(CompileReport(None, (diagnostic,)).valid)
        self.assertTrue(CompileReport(produced, ()).valid)
        with self.assertRaises(ValueError):
            CompileReport(None, ())
        with self.assertRaises(ValueError):
            CompileReport(produced, (diagnostic,))
