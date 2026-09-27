"""Read-only review reproductions against 668506ed; all writes use temporary directories.
Run from repository root with extensions/workbench/.venv/bin/python <this file>.
No market data, engines, external requests, or user databases are used.
"""
import contextlib
import hashlib
import json
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'extensions/workbench'))
sys.path.insert(0, str(ROOT / 'extensions/workbench/tests'))
from quant_workbench import data_directory as dd, factor_pipeline as fp, validation_v2 as vv
from quant_workbench.execution import ExecutionService
from quant_workbench.execution_policy import ExecutionPolicy
from quant_workbench.storage import LocalResultRepository
from sandbox import isolated_repo_root
from test_execution import StubExecutor

results = {}
# Public service routes to this builder without comparing input_basis/calendar.
dates = [f'2020-01-{day:02d}' for day in range(1, 21)]
a = [(.01 if i % 2 else -.004) + i * .0001 for i in range(20)]
b = [(.015 if i % 3 else -.008) - i * .0001 for i in range(20)]
configs = [dict(run_id='a', revision_id='ra', values=a, dates=dates,
                input_basis={'cost_basis': 'before_cost', 'calendar_id': 'calendar-a'}),
           dict(run_id='b', revision_id='rb', values=b, dates=dates,
                input_basis={'cost_basis': 'after_cost', 'calendar_id': 'calendar-b'})]
report = vv.build_report(configs, blocks=4)
results['mixed_validation'] = {'dsr': [r['dsr']['availability'] for r in report['configs']],
    'pbo': report['pbo']['availability'], 'excluded': report['basis']['trial_scope']['excluded'],
    'missing_contract_fields': [key for key in ['return_basis'] if key not in report['basis']]}
results['pipeline_nw'] = {'constant_t': fp.newey_west_t([.1] * 20, 1),
    'gap_t': fp.newey_west_t(a[:10] + [float('nan')] + a[10:], 1)}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    calendar = root / 'calendar.txt'
    calendar.write_text('2020-01-01\n2020-01-02\n')
    digest = 'sha256:' + hashlib.sha256(calendar.read_bytes()).hexdigest()
    record = dd.build_snapshot_record(snapshot_id='fixture', source={'kind': 'fixture'}, components=[
        dict(kind='calendar', uri='calendar.txt', content_digest=digest, source_class='fixture',
             coverage_start='2020-01-01', coverage_end='2020-01-02')])
    dd.publish_snapshot(root/'registry', record)
    calendar.write_text('2021-01-01\n2021-01-02\n')
    loaded = dd.load_snapshot(root/'registry', 'fixture')
    reader = dd.FreeSnapshotReader(root, loaded)
    results['snapshot_mutation'] = {'identity_unchanged': loaded['content_digest'] == record['content_digest'],
        'validation_ok': reader.validate()['ok'], 'read_start': reader.calendar()[0].isoformat()}
with tempfile.TemporaryDirectory() as tmp:
    repo = LocalResultRepository(Path(tmp))
    barrier = threading.Barrier(2)
    original = repo._connection
    class Proxy:
        def __init__(self, conn): self.conn = conn
        def execute(self, sql, args=()):
            cursor = self.conn.execute(sql, args)
            if sql.startswith('SELECT used FROM agent_budget'):
                row = cursor.fetchone()
                barrier.wait(timeout=5)
                return SimpleNamespace(fetchone=lambda: row)
            return cursor
    @contextlib.contextmanager
    def synchronized_connection():
        with original() as conn: yield Proxy(conn)
    repo._connection = synchronized_connection
    def reserve(_):
        return repo.reserve_agent_budget(policy_revision='fixture', scope='scope', kind='trials', limit=1)
    with ThreadPoolExecutor(max_workers=2) as pool: reservations = list(pool.map(reserve, range(2)))
    repo._connection = original
    results['concurrent_trial_budget'] = {'allowed': sum(x['allowed'] for x in reservations),
        'limit': 1, 'durable_used': repo.agent_budget_rows('fixture')[0]['used']}
with tempfile.TemporaryDirectory() as tmp:
    root = isolated_repo_root(tmp)
    repo = LocalResultRepository(root)
    executor = StubExecutor(root)
    policy = ExecutionPolicy(1, 1, 1, 60, 1 << 30, ('cpu',), 2, 10, 'policy_revision')
    service = ExecutionService(repo, [executor], policy=policy)
    attempt = service.submit('stub.sleep', {'seconds': '20'}, idempotency_key='fixture')['attempt']
    aid = attempt['attempt_id']
    try:
        time.sleep(1.3)
        row = repo.get_attempt(aid)  # intentionally no service read/reconcile: supervisor must be autonomous
        process = executor._processes[aid]
        results['timeout_without_reads'] = {'past_deadline': True, 'child_still_running': process.poll() is None,
                                           'recorded_status': row['status']}
        # Model a persisted interrupted classification with termination still unknown.
        repo.update_attempt(aid, status='interrupted', error_code='process_lost_without_exit_evidence')
        results['interrupted_slot'] = {'child_still_running': process.poll() is None,
                                      'open_slots_count': len(repo.list_open_attempts())}
    finally:
        executor.cancel(repo.get_attempt(aid))
        executor._processes.get(aid) and executor._processes[aid].wait(timeout=5)
# Unit fault injection: a dead host wrapper is not evidence that its container ended.
from unittest.mock import patch
from quant_workbench.adapters.executors import SubprocessExecutor
with tempfile.TemporaryDirectory() as tmp:
    executor = SubprocessExecutor(repo_root=isolated_repo_root(tmp))
    calls = []
    executor._remove_container = lambda name: calls.append(name)
    with patch('quant_workbench.adapters.executors._pid_alive', return_value=False):
        result = executor.cancel({'attempt_id': 'fixture-container', 'workspace': tmp, 'pid': 1})
    results['dead_wrapper_cancel'] = {'confirmed': result['confirmed'], 'container_cleanup_calls': len(calls),
                                      'evidence': result.get('evidence')}
print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
