import importlib.util
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1] / 'custom_components/mova_nutripal'
def load(name):
    spec=importlib.util.spec_from_file_location(name,BASE/(name+'.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
cal=load('calibration'); ctrl=load('control'); store=load('state_store'); diag=load('diagnostics_text')

class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.cal=cal.Calibration();self.now=datetime(2026,11,24,6,48,tzinfo=ZoneInfo('Europe/Paris'))
        self.data=dict(online=True,device_status=1,warning_mask=0,fault_mask=0,bowl_weight=1,portions_today=0,intake_today=0,meals_today=0)
    def at(self,sec,**kw):
        self.data.update(kw);return self.cal.observe(self.data,self.now+timedelta(seconds=sec))
    def example(self):
        self.at(0);self.at(30);self.at(60,device_status=2);self.at(90,device_status=1,bowl_weight=55,portions_today=6);self.at(120);self.at(150)
    def test_stable(self):
        self.example();self.assertEqual(self.at(180),9)
    def test_intake_changes(self):
        self.example();self.assertIsNone(self.at(180,intake_today=3))
    def test_weight_changes(self):
        self.example();self.assertIsNone(self.at(180,bowl_weight=50))
    def test_fault(self):
        self.example();self.assertIsNone(self.at(180,fault_mask=1))
    def test_missing(self):
        self.example();self.assertIsNone(self.at(180,meals_today=None))
    def test_timeout(self):
        self.example();self.assertIsNone(self.at(300))
    def test_no_baseline(self):
        self.at(0);self.at(30,bowl_weight=55,portions_today=6);self.at(60);self.assertIsNone(self.at(180))
    def test_midnight(self):
        self.now=self.now.replace(hour=23,minute=59,second=0);self.example();self.assertIsNone(self.at(180))
    def test_outlier(self):
        self.at(0);self.at(30);self.at(60,bowl_weight=150,portions_today=1);self.at(90);self.assertIsNone(self.at(150))
    def test_median(self):
        self.assertEqual(cal.effective_weight([8,9],7),7);self.assertEqual(cal.effective_weight([8,9,12],7),9);self.assertEqual(cal.effective_weight([8,9,12],7,False),7)
    def test_window(self):
        self.assertTrue(cal.near_meal({'schedule':[{'status':True,'feedingTime':'06:50:00'}]},self.now))
        self.assertFalse(cal.near_meal({'schedule':[{'status':True,'feedingTime':'07:50:00'}]},self.now))

class FakeCloud:
    def __init__(self, mode='ok'):
        self.mode=mode;self._conns={'old':object()};self.calls=0
    def _close_conn(self,key):self._conns.pop(key)
    def _http(self,*args):
        assert not self._conns
        self.calls+=1
        if self.mode=='timeout':raise TimeoutError
        return 200,b''
    def send(self,method,params,retry_count,timeout):
        assert method=='action' and params['in']==[{'piid':1,'value':1}] and retry_count==0
        url='https://example.invalid/dreame-iot-com-20000/device/sendCommand'
        if self.mode=='unexpected':url+='V2'
        self._http('POST',url,{},None,timeout)
        if self.mode=='retry':self._http('POST',url,{},None,timeout)
        return {'code':0 if self.mode=='ok' else 1}

class ControlTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,24,10,tzinfo=ZoneInfo('Europe/Paris')); self.state={'pending':None,'last_attempt':0};self.data={'decision':'would_feed','suggested_portions':1};self.options={'manual_enabled':True}
    def test_send(self):
        c=FakeCloud();self.assertTrue(ctrl.send_one(c,'dummy'));self.assertEqual(c.calls,1)
    def test_retry_blocked(self):
        c=FakeCloud('retry');orig=c._http
        with self.assertRaises(RuntimeError):ctrl.send_one(c,'dummy')
        self.assertEqual(c.calls,1);self.assertEqual(c._http,orig)
    def test_timeout(self):
        c=FakeCloud('timeout');orig=c._http
        with self.assertRaises(TimeoutError):ctrl.send_one(c,'dummy')
        self.assertEqual(c.calls,1);self.assertEqual(c._http,orig)
    def test_unexpected(self):
        c=FakeCloud('unexpected')
        with self.assertRaises(RuntimeError):ctrl.send_one(c,'dummy')
        self.assertEqual(c.calls,0)
    def test_not_ack(self):
        c=FakeCloud('failure');self.assertFalse(ctrl.send_one(c,'dummy'))
    def test_permission(self):self.assertEqual(ctrl.manual_allowed(self.data,self.options,self.state,self.now),'ready')
    def test_disabled(self):self.assertEqual(ctrl.manual_allowed(self.data,{},self.state,self.now),'disabled')
    def test_pending(self):
        self.state['pending']={};self.assertEqual(ctrl.manual_allowed(self.data,self.options,self.state,self.now),'pending')
    def test_cooldown(self):
        self.state['last_attempt']=self.now.timestamp()-100;self.assertEqual(ctrl.manual_allowed(self.data,self.options,self.state,self.now),'cooldown')
    def test_budget(self):
        self.data['decision']='budget_reached';self.assertEqual(ctrl.manual_allowed(self.data,self.options,self.state,self.now),'blocked')
    def test_confirmation(self):
        p={'ack':True,'day':self.now.date().isoformat(),'time':self.now.timestamp(),'count':7}; d={'online':True,'device_status':1,'warning_mask':0,'fault_mask':0,'portions_today':8}
        self.assertTrue(ctrl.confirm_pending(p,d,self.now+timedelta(seconds=60)))
        self.assertFalse(ctrl.confirm_pending(p,d,self.now+timedelta(seconds=181)))
        self.assertFalse(ctrl.confirm_pending(p,{**d,'portions_today':9},self.now))
        self.assertFalse(ctrl.confirm_pending({**p,'ack':False},d,self.now))
        self.assertFalse(ctrl.confirm_pending(p,d,self.now+timedelta(days=1)))

class PersistenceTest(unittest.TestCase):
    def test_roundtrip(self):
        state={'samples':[9,8,10],'pending':{'time':123,'count':7,'ack':False,'day':'2026-11-24'},'last_attempt':123,'last_result':'pending'}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';self.assertIsNone(store.load_state(path));store.save_state(path,state);self.assertEqual(store.load_state(path),state)
    def test_corrupt_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';path.write_text('{}')
            with self.assertRaises(ValueError):store.load_state(path)
    def test_unknown_mask(self):
        self.assertIn('Manque de croquettes',diag.mask_messages('warning_mask',2,'fr'))
        self.assertIn('Code non identifié : 4096',diag.mask_messages('warning_mask',4096,'fr'))
