"""Shared publication rules; no engine SDK dependencies."""
import hashlib
import json
import re
from pathlib import Path


class SourceConflict(ValueError):
    pass


def data_nature(declared, effective=None, fixture=False):
    if type(declared) is not bool:
        raise SourceConflict('synthetic declaration must be boolean')
    recorded = effective.get('research', {}).get('synthetic') if effective else None
    if recorded is not None and type(recorded) is not bool:
        raise SourceConflict('invalid recorded data nature')
    if fixture and not declared or recorded is not None and recorded != declared:
        raise SourceConflict('declared data nature conflicts with source evidence')
    return {'synthetic': declared, 'basis': 'source_recorded' if recorded is not None else 'importer_declared'}


def verify_effective(effective, quality=None):
    digest = hashlib.sha256(json.dumps({k:v for k,v in effective.items() if k != 'fingerprint'},
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != effective.get('fingerprint'):
        raise SourceConflict('CN scenario fingerprint mismatch')
    if quality and quality.get('scenario_fingerprint') != digest:
        raise SourceConflict('CN quality scenario mismatch')


def comparison_context(effective):
    return {'execution_id': effective['fingerprint'], 'initial_equity': effective['account']['initial_cash'],
            'cashflow_policy': 'none', 'price_basis': 'qlib_adjusted_account',
            'benchmark_id': effective['research']['benchmark']}


class Sanitizer:
    def __init__(self, root=None):
        self.root = Path(root).resolve() if root else None
        self.secrets = []
        env = self.root / '.env' if self.root else None
        if env and env.is_file():
            for line in env.read_text().splitlines():
                key, sep, value = line.partition('=')
                if sep and re.search(r'KEY|TOKEN|SECRET|PASSWORD', key, re.I):
                    value = value.strip().strip('\"\'')
                    if len(value) > 5:
                        self.secrets.append(value)

    def text(self, value, size=30000):
        s = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            s = s.replace(secret, '[REDACTED]')
        s = re.sub(r'\x1b\[[0-9;]*m', '', s)
        s = re.sub(r'sk-[A-Za-z0-9_-]{8,}', '[REDACTED]', s)
        s = re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1[REDACTED]', s)
        s = re.sub(r'(?i)((?:api[_-]?key|password|token|secret)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', s)
        if self.root:
            s = s.replace(str(self.root), '[SOURCE]')
        s = s.replace(str(Path.home()), '[HOME]')
        return s[:size] + ('\n[内容截断]' if len(s) > size else '')

    def scrub(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(k, 300): '[REDACTED]' if re.search(
                r'(api[_-]?key|password|token|secret|authorization)', k, re.I) else self.scrub(v)
                    for k,v in value.items()}
        if isinstance(value, list):
            return [self.scrub(v) for v in value]
        return value
