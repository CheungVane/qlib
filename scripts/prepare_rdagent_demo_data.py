"""Create RD-Agent factor input from the existing synthetic Qlib CN demo."""

from pathlib import Path

import qlib
from qlib.data import D
from prepare_cn_scenario import dataset_path, load_profile, profile_path
import json
import shutil


PROJECT = Path(__file__).resolve().parents[1]
AGENT = PROJECT.parent / "RD-Agent"
FIELDS = ["$open", "$close", "$high", "$low", "$volume", "$factor"]


def main() -> None:
    bundle = load_profile(profile_path())
    research = bundle['research']
    SOURCE = dataset_path(bundle)
    if not SOURCE.is_dir() or not (AGENT / ".git").exists():
        raise RuntimeError("Qlib CN demo data and sibling RD-Agent checkout are required")
    qlib.init(provider_uri=str(SOURCE), region="cn", kernels=1)
    data = D.features(D.instruments(market=research['market']), FIELDS, freq="day").swaplevel().sort_index()
    if data.empty:
        raise RuntimeError("CN demo data is empty")
    debug_start, debug_end = research['fixture']['debug_range']
    debug = data.loc[debug_start:debug_end]
    if debug.empty:
        raise RuntimeError("CN demo debug window is empty")
    for suffix, frame in (("", data), ("_debug", debug)):
        folder = AGENT / "git_ignore_folder" / f"factor_implementation_source_data{suffix}"
        folder.mkdir(parents=True, exist_ok=True)
        frame.to_hdf(folder / "daily_pv.h5", key="data")
        (folder / "README.md").write_text(
            "# Synthetic China market demo data\nGenerated from the Qlib cn_demo fixture. Integration tests only.\n"
        )
        print(f"{folder.name}: {len(frame)} rows")
    destination = Path.home() / '.qlib/qlib_data/qwb_cn_current' / bundle['fingerprint'][:12]
    if destination.exists():
        if json.loads((destination/'scenario.json').read_text())['fingerprint'] != bundle['fingerprint']:
            raise RuntimeError('Existing provider snapshot differs; preserve it and configure a new provider directory')
    else:
        shutil.copytree(SOURCE, destination)


if __name__ == "__main__":
    main()
