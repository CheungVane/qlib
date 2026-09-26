"""Daily CN cash-equity adapter, isolated from upstream Qlib source."""
import math
import json
from pathlib import Path

import pandas as pd
from qlib.backtest.decision import Order
from qlib.backtest.exchange import Exchange
from qlib.workflow.record_temp import RecordTemp

from quant_workbench.cn_market import fees, order_quantity, sessions, validate


class ConfiguredCNExchange(Exchange):
    def __init__(self, scenario, instruments, fee_ledger_path=None, **kwargs):
        validate(scenario)
        self.scenario = scenario
        self.instruments = instruments
        self._bought_today = {}
        self.fee_records = []
        self.fee_ledger_path = Path(fee_ledger_path) if fee_ledger_path else None
        if self.fee_ledger_path:
            self.fee_ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.fee_ledger_path.write_text("")
        if kwargs.get("freq", "day") != "day":
            raise ValueError("CN adapter supports daily execution only")
        execution = scenario["research"]["execution"]
        kwargs.update(
            codes=list(instruments), deal_price=execution["deal_price"],
            limit_threshold=("$buy_blocked", "$sell_blocked"),
            volume_threshold=("cum", f"$volume * {execution['volume_participation']}"),
            trade_unit=None, open_cost=0, close_cost=0, min_cost=0, impact_cost=0,
        )
        super().__init__(**kwargs)
        if self.quote_df[["$factor", "$volume", "$buy_blocked", "$sell_blocked"]].isna().any().any():
            raise ValueError("Missing factor/volume/tradability data; no silent fallback")
        if (self.quote_df["$factor"] <= 0).any():
            raise ValueError("Invalid adjustment factor")

    def _calc_trade_info_by_order(self, order, position, dealt_order_amount):
        if position is None:
            raise ValueError("A position is required for cash and T+1 checks")
        start, end = pd.Timestamp(order.start_time), pd.Timestamp(order.end_time)
        trading_days = sessions(self.scenario['calendar'], start.date(), end.date())
        # Qlib's daily bar may end on the following weekend/holiday.
        if trading_days != [start.date().isoformat()]:
            raise ValueError("Orders covering multiple trading sessions are unsupported")
        state = self.instruments[order.stock_id]
        if state["status"] not in self.scenario["research"]["supported_status"]:
            raise ValueError("Unsupported security status")
        if state["board"] not in self.scenario["research"]["enabled_boards"]:
            raise ValueError("Board not enabled")
        board = self.scenario["rules"]["boards"][state["board"]]
        price = float(self.get_deal_price(order.stock_id, start, end, direction=order.direction))
        factor = float(self.get_factor(order.stock_id, start, end))
        if not math.isfinite(price) or price <= 0 or not math.isfinite(factor) or factor <= 0:
            raise ValueError("Invalid execution price/factor")
        order.factor = factor
        order.deal_amount = order.amount
        self._clip_amount_by_volume(order, dealt_order_amount)
        requested = max(0, math.floor(order.deal_amount * factor + 1e-6))
        side = "buy" if order.direction == Order.BUY else "sell"
        key = (id(position), order.stock_id)
        old_date, bought = self._bought_today.get(key, (None, 0.0))
        if old_date != start.date():
            bought = 0.0
        available = None
        if side == "sell":
            held = position.get_stock_amount(order.stock_id) if position.check_stock(order.stock_id) else 0
            available = max(0, math.floor((held - bought) * factor + 1e-6))
        quantity = order_quantity(requested, board, side, available)

        def total(q):
            value = q / factor * price
            return value + float(fees(value, side, self.scenario)["total"])

        # Exact cost-aware sizing, including rounded minimum commission and
        # separate taxes. Binary search raw shares, then enforce board quantities.
        if side == "buy" and total(quantity) > position.get_cash():
            low, high = 0, quantity
            while low < high:
                mid = (low + high + 1) // 2
                if total(mid) <= position.get_cash():
                    low = mid
                else:
                    high = mid - 1
            quantity = order_quantity(low, board, side)
        value = quantity / factor * price
        breakdown = fees(value, side, self.scenario)
        if side == "sell" and position.get_cash() + value < float(breakdown["total"]):
            quantity, value = 0, 0.0
            breakdown = fees(0, side, self.scenario)
        order.deal_amount = quantity / factor
        if side == "buy" and quantity:
            self._bought_today[key] = (start.date(), bought + order.deal_amount)
        if quantity:
            self.fee_records.append({"instrument": order.stock_id, "date": start.date().isoformat(),
                                     "side": side, "raw_shares": quantity,
                                     **{k: str(v) for k, v in breakdown.items()}})
            if self.fee_ledger_path:
                with self.fee_ledger_path.open("a") as stream:
                    stream.write(json.dumps(self.fee_records[-1]) + "\n")
        return price, value, float(breakdown["total"])


class CNQualityRecord(RecordTemp):
    """Separate artifact/process success from research quality, without hiding failures."""
    def __init__(self, recorder, scenario, output_path):
        super().__init__(recorder)
        self.scenario = scenario
        self.output_path = Path(output_path)

    def generate(self, **kwargs):
        pred = self.recorder.load_object('pred.pkl').iloc[:, 0].rename('prediction')
        label = self.recorder.load_object('label.pkl').iloc[:, 0].rename('label')
        frame = pd.concat([pred, label], axis=1).dropna()
        threshold = self.scenario['research']['quality']
        groups = list(frame.groupby(level='datetime'))
        valid = sum(len(g) >= threshold['min_cross_section'] and g.prediction.nunique() > 1
                    and g.label.nunique() > 1 and math.isfinite(g.prediction.corr(g.label)) for _, g in groups)
        constant = sum(g.prediction.nunique() <= 1 for _, g in groups)
        report = self.recorder.load_object('portfolio_analysis/report_normal_1day.pkl')
        trade_days = int(report.turnover.fillna(0).ne(0).sum())
        reasons = []
        if valid < threshold['min_valid_ic_days']:
            reasons.append('insufficient_valid_ic_days')
        if trade_days < threshold['min_trade_days']:
            reasons.append('insufficient_trade_days')
        result = {'schema_version': 1, 'scenario_fingerprint': self.scenario['fingerprint'],
                  'synthetic': self.scenario['research']['synthetic'],
                  'status': 'failed_checks' if reasons else 'passed_checks',
                  'valid_ic_days': int(valid), 'constant_prediction_days': int(constant),
                  'trade_days': trade_days, 'reasons': reasons,
                  'note': 'Passing checks is not evidence of alpha or live readiness.'}
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(result, indent=2) + '\n')
        self.recorder.log_artifact(str(self.output_path), artifact_path='cn_quality')
        self.recorder.set_tags(cn_quality_status=result['status'], cn_scenario=self.scenario['fingerprint'],
                               cn_mode=self.scenario['research']['mode'])
        effective = self.output_path.parent / 'effective.json'
        if not effective.exists():
            effective.write_text(json.dumps(self.scenario, ensure_ascii=False, indent=2) + '\n')
        self.recorder.log_artifact(str(effective), artifact_path='cn_quality')
        ledger = self.output_path.parent / ('fees.jsonl' if self.output_path.name == 'quality.json' else 'cn_fee_ledger.jsonl')
        if ledger.exists():
            self.recorder.log_artifact(str(ledger), artifact_path='cn_quality')
        print('CN_QUALITY', json.dumps(result))
