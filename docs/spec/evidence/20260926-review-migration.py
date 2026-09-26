import sqlite3,tempfile,hashlib,json
from pathlib import Path
from mlflow.tracking import MlflowClient
root=Path.cwd();src=root/'.data/qlib_mlruns_mlflow3_12.db'
before=hashlib.sha256(src.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as tmp:
 dest=Path(tmp)/'copy.db'
 with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(dest) as copy:source.backup(copy)
 def version():
  with sqlite3.connect(dest) as db:return db.execute('select version_num from alembic_version').fetchone()[0]
 old=version();client=MlflowClient(tracking_uri='sqlite:///'+str(dest));client.get_experiment_by_name('workflow')
 print(json.dumps({'copy_schema_before':old,'copy_schema_after_read':version(),'source_sha256_unchanged':before==hashlib.sha256(src.read_bytes()).hexdigest()}))
