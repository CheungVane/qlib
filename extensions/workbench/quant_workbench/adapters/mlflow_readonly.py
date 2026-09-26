"""MLflow may migrate on reads. Only ever give its SDK disposable metadata."""
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, unquote
import shutil
import sqlite3
import tempfile


@contextmanager
def isolated_mlflow_client(tracking_uri):
    parsed = urlparse(tracking_uri)
    if parsed.scheme not in ('', 'file', 'sqlite') or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('only plain local file/SQLite tracking URIs are supported')
    with tempfile.TemporaryDirectory(prefix='qwb-mlflow-read-') as tmp:
        if parsed.scheme == 'sqlite':
            if not tracking_uri.startswith('sqlite:///'):
                raise ValueError('invalid SQLite tracking URI')
            source = Path(unquote(tracking_uri[len('sqlite:///'):])).expanduser().resolve(strict=True)
            target = Path(tmp) / 'tracking.db'
            with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src:
                with sqlite3.connect(target) as dst:
                    src.backup(dst)
            uri = 'sqlite:///' + str(target)
        else:
            source = Path(unquote(parsed.path)).expanduser().resolve(strict=True)
            target = Path(tmp) / 'tracking'
            # Artifact URIs in metadata still refer to trusted source artifacts;
            # copying their bytes also supports old relative file-store layouts.
            shutil.copytree(source, target)
            uri = target.as_uri()
        from mlflow.tracking import MlflowClient
        yield MlflowClient(tracking_uri=uri)
