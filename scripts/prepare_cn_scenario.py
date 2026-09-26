"""Compile independent CN JSON profiles into Qlib and RD-Agent YAML configurations."""
import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'extensions/workbench'))
from quant_workbench.cn_market import effective_segments, load_profile


def profile_path():
    return Path(os.environ.get('QWB_CN_PROFILE', PROJECT / 'configs/cn/profile.json'))


def instruments(bundle):
    fixture = bundle['research']['fixture']
    return {f"{fixture['stock_prefix']}{i:03d}": {'board': fixture['board'], 'status': 'normal'}
            for i in range(fixture['stock_count'])}


def dataset_path(bundle):
    return PROJECT / bundle['research']['data_path'] / bundle['fingerprint'][:12]


def apply_scenario(config, bundle, provider, ledger):
    r = bundle['research']
    segments = effective_segments(bundle)
    config['qlib_init']['provider_uri'] = provider
    config['qlib_init']['region'] = 'cn'
    config['qlib_init']['kernels'] = 1
    config['market'], config['benchmark'] = r['market'], r['benchmark']
    handler = config['task']['dataset']['kwargs']['handler']['kwargs']
    handler.update(start_time=r['date_range'][0], end_time=r['date_range'][1], instruments=r['market'])
    if 'fit_start_time' in handler:
        handler.update(fit_start_time=segments['train'][0], fit_end_time=segments['train'][1])
    for processor in handler.get('infer_processors', []) + handler.get('learn_processors', []):
        if isinstance(processor, dict) and 'fit_start_time' in processor.get('kwargs', {}):
            processor['kwargs'].update(fit_start_time=segments['train'][0], fit_end_time=segments['train'][1])
    config['task']['dataset']['kwargs']['segments'] = segments
    model = config['task']['model']
    if model['class'] != 'LGBModel':
        raise ValueError('Only the LGBModel scenario is verified; refusing an unconfigured model template')
    model['kwargs'].update(r['model'])
    port = config['port_analysis_config']
    port['strategy']['kwargs'].update(r['strategy'])
    port['strategy']['kwargs']['forbid_all_trade_at_limit'] = r['execution']['forbid_all_trade_at_limit']
    bt = port['backtest']
    bt.update(start_time=segments['test'][0], end_time=segments['test'][1],
              account=bundle['account']['initial_cash'], benchmark=r['benchmark'])
    bt['exchange_kwargs'] = {'exchange': {'class': 'ConfiguredCNExchange',
        'module_path': 'quant_workbench.adapters.qlib_cn',
        'kwargs': {'scenario': bundle, 'instruments': instruments(bundle), 'freq': 'day',
                   'start_time': bt['start_time'], 'end_time': bt['end_time'], 'fee_ledger_path': ledger}}}
    for record in config['task']['record']:
        if record['class'] == 'SigAnaRecord':
            record['kwargs']['ann_scaler'] = r['annualization']['signal_days']
        if record['class'] == 'PortAnaRecord':
            record['kwargs']['config'] = port
    quality_path = str(Path(ledger).parent / ('quality.json' if Path(ledger).name == 'fees.jsonl' else 'cn_quality.json'))
    config['task']['record'].append({'class': 'CNQualityRecord', 'module_path': 'quant_workbench.adapters.qlib_cn',
                                    'kwargs': {'scenario': bundle, 'output_path': quality_path}})
    config['qwb_scenario'] = {'fingerprint': bundle['fingerprint'], 'mode': r['mode'],
                             'rules_as_of': bundle['rules']['as_of'], 'synthetic': r['synthetic'],
                             'effective_segments': segments, 'unsupported': r['unsupported']}
    return config


def compile_qlib(bundle, out_dir=None):
    target = Path(out_dir) if out_dir is not None else (
        PROJECT / '.data/cn_runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '-' + bundle['fingerprint'][:10]))
    target.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((PROJECT / 'examples/benchmarks/LightGBM/workflow_config_cn_demo.yaml').read_text())
    config['sys'] = {'path': [str(PROJECT / 'extensions/workbench')]}
    apply_scenario(config, bundle, str(dataset_path(bundle)), str(target / 'fees.jsonl'))
    if out_dir is not None:
        # Workbench attempts get their own experiment store so two configurations never share runs.
        config['qlib_init']['exp_manager']['kwargs']['uri'] = f'sqlite:///{target}/mlflow.db'
    (target / 'effective.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+'\n')
    (target / 'workflow.yaml').write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    return target / 'workflow.yaml'


def compile_agent(bundle):
    agent = PROJECT.parent / 'RD-Agent'
    source = agent / 'rdagent/scenarios/qlib/experiment/factor_template'
    # Versioned directory keeps previous runs/templates intact.
    target = agent / 'git_ignore_folder' / ('qwb_cn_factor_template_' + bundle['fingerprint'][:12])
    target.mkdir(parents=True, exist_ok=True)
    for name in ('conf_baseline.yaml', 'conf_combined_factors.yaml'):
        tokens = {}
        def protect(match):
            token = 'QWB_JINJA_' + str(len(tokens))
            tokens[token] = match.group(0)
            return token
        raw = re.sub(r'\{\{.*?\}\}', protect, (source/name).read_text())
        config = yaml.safe_load(raw)
        config['sys'] = {'path': ['/opt/qwb']}
        # Use a separate provider directory; never overwrite existing cn_data.
        apply_scenario(config, bundle, '~/.qlib/qlib_data/qwb_cn_current/' + bundle['fingerprint'][:12], 'cn_fee_ledger.jsonl')
        text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        for token, expression in tokens.items():
            # Dates were materialized above; remaining tokens are feature expressions/names.
            text = text.replace(token, expression)
        (target/name).write_text(text)
    for name in ('read_exp_res.py', 'README.md'):
        (target/name).write_bytes((source/name).read_bytes())
    (target/'effective.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2)+'\n')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', type=Path, default=profile_path())
    parser.add_argument('--target', choices=['qlib','rdagent'], default='qlib')
    parser.add_argument('--out-dir', type=Path, help='write the compiled Qlib workflow into this directory')
    args = parser.parse_args()
    if args.out_dir is not None and args.target != 'qlib':
        parser.error('--out-dir is only supported for --target qlib')
    b = load_profile(args.profile)
    print(compile_qlib(b, args.out_dir) if args.target == 'qlib' else compile_agent(b))
