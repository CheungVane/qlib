import copy
import unittest
from pathlib import Path
from decimal import Decimal
from quant_workbench.cn_market import load_profile, fees, order_quantity, sessions, effective_segments, quality_summary, validate, price_limits

ROOT = Path(__file__).resolve().parents[3]

class CNMarketTests(unittest.TestCase):
    def setUp(self):
        self.b = load_profile(ROOT/'configs/cn/profile.json')

    def test_separate_minimum_commission_and_taxes(self):
        buy, sell = fees(10000,'buy',self.b), fees(10000,'sell',self.b)
        self.assertEqual(buy['commission'],Decimal('5'))
        self.assertEqual(buy['transfer'],Decimal('0.10'))
        self.assertEqual(sell['stamp'],Decimal('5'))
        self.assertEqual(sell['total']-sell['slippage'],Decimal('10.10'))
        self.assertEqual(fees(0,'sell',self.b)['total'],0)
        b=copy.deepcopy(self.b); b['account']['commission_includes_transfer_fee']=True
        self.assertEqual(fees(10000,'buy',b)['transfer'],0)

    def test_exchange_holidays_and_label_purge(self):
        cal=self.b['calendar']
        self.assertEqual(sessions(cal,'2020-01-24','2020-02-03'),['2020-02-03'])
        self.assertEqual(sessions(cal,'2021-10-01','2021-10-08'),['2021-10-08'])
        with self.assertRaises(ValueError): sessions(cal,'2026-01-01','2026-01-05')
        segments=effective_segments(self.b)
        self.assertEqual(segments['train'][1],'2020-12-29')
        self.assertEqual(segments['valid'][1],'2021-06-28')
        self.assertEqual(segments['test'][1],'2021-12-29')

    def test_board_lots_and_odd_lot_liquidation(self):
        boards=self.b['rules']['boards']
        self.assertEqual(order_quantity(201,boards['star'],'buy'),201)
        self.assertEqual(order_quantity(199,boards['star'],'buy'),0)
        self.assertEqual(order_quantity(101,boards['bse'],'buy'),101)
        self.assertEqual(order_quantity(101,boards['sse_main'],'buy'),100)
        self.assertEqual(order_quantity(199,boards['star'],'sell',199),199)
        self.assertEqual(order_quantity(99,boards['star'],'sell',199),0)

    def test_quality_not_inferred_from_process_success(self):
        q=quality_summary({'IC':float('nan')},1,self.b['research']['quality'])
        self.assertFalse(q['research_valid'])
        self.assertIn('insufficient_trade_days',q['reasons'])

    def test_invalid_configuration_fails_closed(self):
        for field, value in [('synthetic',False),('mode','historical'),('supported_status',['normal','st'])]:
            b=copy.deepcopy(self.b); b['research'][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): validate(b)
        b=copy.deepcopy(self.b); b['research']['execution']['slipage_bps']='3'
        with self.assertRaises(ValueError): validate(b)
        self.assertEqual(price_limits('10.01',self.b['rules']['boards']['sse_main'],'0.01'),
                         (Decimal('9.01'),Decimal('11.01')))

    def test_t1_cash_and_volume(self):
        try:
            import pandas as pd
            from qlib.backtest.position import Position
            from qlib.backtest.decision import Order
            from quant_workbench.adapters.qlib_cn import ConfiguredCNExchange
        except ImportError:
            self.skipTest('Qlib adapter test requires Qlib environment')
        ex=ConfiguredCNExchange.__new__(ConfiguredCNExchange)
        ex.scenario=self.b; ex.instruments={'SH600000':{'board':'sse_main','status':'normal'}}
        ex._bought_today={}; ex.fee_records=[]; ex.fee_ledger_path=None
        ex.get_deal_price=lambda *a,**k:10.0
        ex.get_factor=lambda *a,**k:1.0
        cap=[100000]
        def clip(o,dealt): o.deal_amount=min(o.deal_amount,cap[0])
        ex._clip_amount_by_volume=clip
        pos=Position(cash=100000,position_dict={'SH600000':{'amount':300,'price':10}})
        def trade(side,amount,day):
            o=Order('SH600000',amount,side,pd.Timestamp(day),pd.Timestamp(day)+pd.Timedelta(hours=23))
            price,value,cost=ex._calc_trade_info_by_order(o,pos,{})
            if value: pos.update_order(o,value,cost,price)
            return o.deal_amount
        self.assertEqual(trade(Order.BUY,100,'2021-07-01'),100)
        self.assertEqual(trade(Order.SELL,400,'2021-07-01'),300)
        self.assertEqual(trade(Order.SELL,100,'2021-07-02'),100)
        cap[0]=150
        self.assertEqual(trade(Order.BUY,1000,'2021-07-02'),100)
        cap[0]=100000
        pos.position['cash']=1005.0
        self.assertEqual(trade(Order.BUY,100,'2021-07-05'),0)

if __name__=='__main__': unittest.main()
