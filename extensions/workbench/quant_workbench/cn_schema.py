"""Closed, typed configuration schema for the verified daily CN compiler.

Keys are schema, not parameter defaults; values remain in configs/cn.
"""
from datetime import date, time
from decimal import Decimal, InvalidOperation

TEXT = 'text'
DATE_PAIR = ['date', 'date']
BOARD = dict(limit='rate', st_limit='rate', buy_min='positive_int', step='positive_int', max_order='positive_int')
SHAPES = {
    'rules': dict(schema_version='v1', id=TEXT, as_of='date', effective_from='date', timezone=TEXT,
                  scope=TEXT, tick_size='positive_decimal', share_settlement_days='positive_int',
                  fees=dict(stamp_sell='rate', transfer_both='rate', rounding_unit='positive_decimal'),
                  boards={k:BOARD for k in ('sse_main','szse_main','star','chinext','bse')},
                  sources=('list',TEXT), verification_notes=('list',TEXT)),
    'account': dict(schema_version='v1', commission_both='rate', minimum_commission='nonnegative_decimal',
                    commission_includes_regulatory_fees='bool', commission_includes_transfer_fee='bool',
                    initial_cash='positive_number', assumptions=('list',TEXT)),
    'calendar': dict(schema_version='v1', id=TEXT, timezone=TEXT, coverage=DATE_PAIR,
                     weekdays=('list','weekday'), closed_ranges=('list',DATE_PAIR),
                     sessions={k:['time','time'] for k in ('opening_auction','continuous_am','continuous_pm','closing_auction')},
                     sources=('list',TEXT)),
    'research': dict(schema_version='v1', mode=TEXT, synthetic='bool', enabled_boards=('list',TEXT),
                     supported_status=('list',TEXT), market=TEXT, benchmark=TEXT, data_path=TEXT,
                     date_range=DATE_PAIR, segments={k:DATE_PAIR for k in ('train','valid','test')},
                     label=dict(expression=TEXT,future_bars='positive_int'),
                     execution=dict(deal_price=TEXT,volume_participation='positive_rate',slippage_bps='bps',
                                    forbid_all_trade_at_limit='bool',require_factor='bool'),
                     strategy=dict(topk='positive_int',n_drop='nonnegative_int',hold_thresh='nonnegative_int',only_tradable='bool'),
                     model=dict(num_threads='positive_int',num_leaves='positive_int',learning_rate='positive_rate',
                                num_boost_round='positive_int',early_stopping_rounds='positive_int',
                                lambda_l1='nonnegative_number',lambda_l2='nonnegative_number'),
                     quality=dict(min_valid_ic_days='positive_int',min_trade_days='positive_int',min_cross_section='positive_int'),
                     fixture=dict(seed='nonnegative_int',stock_count='positive_int',stock_prefix=TEXT,board=TEXT,
                                  factor='positive_decimal',debug_range=DATE_PAIR),
                     agent=dict(evolving_n='positive_int',coder_max_loop='positive_int'),
                     annualization=dict(signal_days='positive_int',native_portfolio_days='positive_int'),
                     unsupported=('list',TEXT))}


def check(value, shape, path='config'):
    def fail(): raise ValueError(f'Invalid configuration field: {path}')
    if isinstance(shape, dict):
        if not isinstance(value, dict) or set(value) != set(shape): fail()
        for k,s in shape.items(): check(value[k],s,path+'.'+k)
    elif isinstance(shape, tuple):
        if not isinstance(value, list): fail()
        for i,v in enumerate(value): check(v,shape[1],f'{path}[{i}]')
    elif isinstance(shape, list):
        if not isinstance(value,list) or len(value) != len(shape): fail()
        for i,(v,s) in enumerate(zip(value,shape)): check(v,s,f'{path}[{i}]')
        if shape in (DATE_PAIR,['time','time']) and value[0] > value[1]: fail()
    elif shape in ('text','date','time'):
        if not isinstance(value,str) or not value.strip(): fail()
        if shape == 'date':
            if date.fromisoformat(value).isoformat() != value: fail()
        if shape == 'time': time.fromisoformat(value)
    elif shape == 'bool':
        if type(value) is not bool: fail()
    elif shape in ('positive_int','nonnegative_int','weekday','v1'):
        if type(value) is not int: fail()
        if shape == 'v1' and value != 1: fail()
        if shape == 'weekday' and not 0 <= value <= 6: fail()
        if shape == 'positive_int' and value <= 0: fail()
        if shape == 'nonnegative_int' and value < 0: fail()
    else:
        if isinstance(value,bool) or type(value) not in (int,float,str): fail()
        if shape.endswith('_number') and type(value) not in (int,float): fail()
        try: n=Decimal(str(value))
        except InvalidOperation: fail()
        if not n.is_finite() or n < 0: fail()
        if shape.startswith('positive') and n <= 0: fail()
        if shape == 'rate' and n >= 1: fail()
        if shape == 'positive_rate' and n > 1: fail()
        if shape == 'bps' and n >= 10000: fail()


def validate_shapes(bundle):
    from .cn_market import DERIVED_IDENTITY_KEYS
    allowed = {frozenset(SHAPES)}
    for extra in ({'fingerprint'}, set(DERIVED_IDENTITY_KEYS)):
        allowed.add(frozenset(set(SHAPES) | extra))
    if frozenset(bundle) not in allowed:
        raise ValueError('Unknown or missing scenario fields')
    for name,shape in SHAPES.items(): check(bundle[name],shape,name)
    r,c,a=bundle['research'],bundle['calendar'],bundle['rules']
    if a['timezone'] != 'Asia/Shanghai' or c['timezone'] != a['timezone'] or a['scope'] != 'cash_equity_regular_auction':
        raise ValueError('Unsupported market timezone/scope')
    if Decimal(str(a['fees']['rounding_unit'])) != Decimal('.01') or Decimal(str(a['tick_size'])) != Decimal('.01'):
        raise ValueError('Only cent rounding/ticks verified for this adapter')
    if r['annualization']['native_portfolio_days'] != 238:
        raise ValueError('Native portfolio annualization is 238; cannot override by configuration')
    if not c['weekdays'] or len(set(c['weekdays'])) != len(c['weekdays']):
        raise ValueError('Invalid calendar weekdays')
    if not r['enabled_boards'] or len(set(r['enabled_boards'])) != len(r['enabled_boards']):
        raise ValueError('Invalid enabled boards')
    for board in a['boards'].values():
        if board['max_order'] < board['buy_min']: raise ValueError('Board max_order below minimum')
    for bounds in list(r['segments'].values())+[r['fixture']['debug_range']]:
        if not r['date_range'][0] <= bounds[0] <= bounds[1] <= r['date_range'][1]:
            raise ValueError('Research segment outside dataset range')
