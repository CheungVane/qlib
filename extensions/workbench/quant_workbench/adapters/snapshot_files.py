"""Version-2 manifests and verified byte reads. No engine or service dependencies."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

from ..domain.errors import SnapshotError


def digest(value) -> str:
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def record_digest(record: dict) -> str:
    return digest({k: v for k, v in record.items() if k not in ('content_digest', 'created_at')})


def safe_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('unsafe component path')
    target = root
    for part in path.parts:
        target = target / part
        if target.is_symlink():
            raise ValueError('symlink component forbidden')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('component outside data root')
    return target


def file_entry(path: Path, relative: str) -> dict:
    data = path.read_bytes()
    return {'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}


def seal_record(root: Path, record: dict, interpretation: dict, quality: dict) -> dict:
    """Create a NEW identity from observed bytes, never upgrade a historical identity in place."""
    result = deepcopy(record)
    result.update(schema_version=2, interpretation=interpretation, quality=quality)
    for item in result['components']:
        target = safe_path(root, item['uri'])
        paths = sorted(target.rglob('*')) if target.is_dir() else [target]
        entries = []
        for path in paths:
            if path.is_symlink():
                raise ValueError('cannot seal symlinks')
            if path.is_file():
                entries.append(file_entry(path, path.relative_to(target).as_posix() if target.is_dir() else '.'))
        if not entries:
            raise ValueError('empty component')
        item['files'] = entries
        item['content_digest'] = digest(entries)
    result['content_digest'] = record_digest(result)
    return result


class VerifiedFiles:
    """Parse only returned bytes; never verify then reopen a path to parse it."""
    def __init__(self, root: Path, record: dict):
        self.root, self.record = Path(root), deepcopy(record)
        self.snapshot_id = record.get('snapshot_id', 'unknown')
        if record.get('status') != 'published':
            self.fail('snapshot_not_published')
        if record.get('schema_version') != 2 or not record.get('interpretation'):
            self.fail('snapshot_unverified')
        if record.get('content_digest') != record_digest(record):
            self.fail('snapshot_content_mismatch')
        if record.get('quality', {}).get('passed') is not True:
            self.fail('snapshot_unverified')
        self.entries = {}
        for component in record.get('components', []):
            kind = component['kind']
            files = component.get('files', [])
            if not files or component.get('content_digest') != digest(files) or kind in self.entries:
                self.fail('snapshot_unverified', kind)
            if [e.get("path", "") for e in files] != sorted(e.get("path", "") for e in files):
                self.fail("snapshot_unverified", kind)
            mapped = {}
            for entry in files:
                name = entry.get('path', '')
                sha = entry.get('sha256', '')
                if name in mapped or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) \
                        or type(entry.get('size_bytes')) is not int or entry['size_bytes'] < 0:
                    self.fail('snapshot_unverified', kind)
                try:
                    safe_path(self.root, component['uri'])
                    if name != '.':
                        safe_path(self.root, name)
                except ValueError:
                    self.fail('snapshot_unverified', kind)
                mapped[name] = entry
            self.entries[kind] = (component['uri'], mapped)
        self.cache = OrderedDict()
        self.cache_size = 0

    def fail(self, code, component=None):
        raise SnapshotError(code, self.snapshot_id, component)

    def read(self, kind: str, name: str = '.') -> bytes:
        if kind not in self.entries or name not in self.entries[kind][1]:
            self.fail('snapshot_component_missing', f'{kind}/{name}')
        key = (kind, name)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]  # cached immutable bytes belong to the verified content identity
        uri, entries = self.entries[kind]
        entry = entries[name]
        try:
            base = safe_path(self.root, uri)
            path = base if name == '.' else safe_path(base, name)
            data = path.read_bytes()
        except OSError:
            self.fail('snapshot_component_missing', f'{kind}/{name}')
        except ValueError:
            self.fail('snapshot_content_mismatch', f'{kind}/{name}')
        if len(data) != entry['size_bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            self.fail('snapshot_content_mismatch', f'{kind}/{name}')
        if len(data) <= 32 * 1024 * 1024:
            while self.cache and self.cache_size + len(data) > 32 * 1024 * 1024:
                _, old = self.cache.popitem(last=False)
                self.cache_size -= len(old)
            self.cache[key] = data
            self.cache_size += len(data)
        return data

    def verify_all(self) -> dict:
        count = size = 0
        for kind, (_, entries) in self.entries.items():
            for name in entries:
                value = self.read(kind, name)
                count += 1
                size += len(value)
        return {'files': count, 'bytes': size, 'content_digest': self.record['content_digest']}


def atomic_create(target: Path, payload: bytes) -> None:
    """A complete file appears atomically, and a concurrent writer cannot overwrite it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
