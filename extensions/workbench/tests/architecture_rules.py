"""Static boundary checks. Not a runtime sandbox or complete type checker.

Legacy exceptions are exact module edges, not a blanket permission for new IO.
See docs/spec/ARCHITECTURE.md for migration ownership and acceptance boundaries.
"""
import ast
import importlib.util

TOP_LEVEL = set('''__init__ api application bootstrap cli maintenance cn_market cn_schema dashboard
 data_directory dto execution execution_policy factor_pipeline factors factors_v2 free_sources
 metrics model numeric provenance research research_lifecycle risk risk_v2 series_view
 source_safety storage storage_attempts storage_base storage_factors storage_results telemetry
 validation validation_v2'''.split())
PURE_STDLIB = {'__future__', 'dataclasses', 'enum', 'typing', 'collections', 'datetime',
               'struct', 'hashlib', 'json', 'math', 're', 'decimal', 'pathlib', 'uuid'}
# Removing these edges is allowed. Adding an edge requires an architecture review.
LEGACY = {
    'services.results': {'provenance', 'metrics', 'research'},
    'services.comparison': {'metrics'},
    'services.factors': {'factors', 'factors_v2'},
    'services.risk': {'risk', 'risk_v2', 'series_view'},
    'services.validation': {'validation', 'validation_v2', 'risk_v2', 'series_view'},
    'services.attention': {'factors'},
    'services.execution': {'source_safety', 'execution_policy'},
}
COMPAT = {
    'execution': 'services.execution', 'research_lifecycle': 'domain.research',
    **{name: 'adapters.storage.' + name for name in
       ('storage', 'storage_base', 'storage_attempts', 'storage_results', 'storage_factors')},
}


def imports(module, tree):
    package = 'quant_workbench.' + module.rpartition('.')[0]
    package = package.rstrip('.')
    if module.endswith('.__init__'):
        package = 'quant_workbench.' + module.removesuffix('.__init__')
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = importlib.util.resolve_name('.' * node.level + base, package)
            if node.module:
                yield base
            else:
                yield from (base + '.' + a.name for a in node.names)


def violations(module, source):
    tree = ast.parse(source)
    errors = []
    layer = module.split('.')[0]
    if '.' not in module and module not in TOP_LEVEL:
        errors.append('new flat module: choose an owned package')
    deps = list(imports(module, tree))
    if module in COMPAT:
        expected = 'quant_workbench.' + COMPAT[module]
        if deps != [expected] or any(not (isinstance(n, ast.ImportFrom) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))) for n in tree.body):
            errors.append('compatibility module must only re-export its canonical implementation')
    for dep in deps:
        internal = dep.startswith('quant_workbench.')
        target = dep.removeprefix('quant_workbench.')
        target_layer = target.split('.')[0]
        if layer in {'domain', 'ports', 'services'}:
            allowed = {'domain'} | ({'ports'} if layer != 'domain' else set()) | ({'services'} if layer == 'services' else set())
            if internal:
                if target_layer not in allowed and target not in LEGACY.get(module, set()):
                    errors.append('forbidden dependency: ' + dep)
            elif dep.split('.')[0] not in PURE_STDLIB:
                errors.append('non-core dependency: ' + dep)
        # Managed entry ownership: one Run owner, one execution admission owner.
        managed_allowed = {
            'services.data_pipeline': {'services.research_runs'},
            'services.research_workflows': {'services.research_runs'},
            'services.research_runs': set(),
        }
        if module in managed_allowed and internal:
            if target_layer == 'services' and target not in managed_allowed[module]:
                errors.append('managed entry bypasses Run ownership: ' + dep)
            if module != 'services.research_runs' and target_layer == 'ports':
                errors.append('domain entry bypasses Run transaction boundary: ' + dep)
        if module == 'services.research_runs' and target_layer == 'ports' and target != 'ports.research':
            errors.append('Run owner imports unrelated persistence: ' + dep)
        if layer == 'adapters' and internal and target_layer in {
                'application', 'bootstrap', 'api', 'cli', 'services', *COMPAT}:
            errors.append('adapter depends on orchestration/compatibility: ' + dep)
        if module in {'application', 'api', 'cli'} and internal:
            if target_layer == 'adapters' and not (module == 'cli' and target in {
                    'adapters.json_result', 'adapters.qlib_mlflow'}):
                errors.append('entry/facade assembles infrastructure: ' + dep)
            if target_layer in COMPAT:
                errors.append('new orchestration must use canonical modules: ' + dep)
        if module in {'api', 'cli'} and (target.startswith('adapters.storage') or
                target_layer in {'sqlite3', 'storage', 'storage_base', 'storage_results',
                                 'storage_attempts', 'storage_factors', 'qlib', 'mlflow'}):
            errors.append('entry point bypasses service boundary: ' + dep)
    if layer in {'domain', 'ports', 'services'}:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name in {'__import__', 'importlib.import_module', 'open'} or name.endswith(
                        ('.read_text', '.read_bytes', '.write_text', '.write_bytes', '.mkdir', '.unlink')):
                    errors.append('core direct IO/dynamic import: ' + name)
    return errors
