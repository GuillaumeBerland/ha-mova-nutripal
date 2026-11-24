import importlib.util
from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('planner', Path(__file__).resolve().parents[1] / 'custom_components/mova_nutripal/planner.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 24, 9, 45, tzinfo=ZoneInfo('Europe/Paris'))
        self.opts = dict(target=100, portion_weight=9, threshold=5, max_complement=3)
        self.data = dict(portions_today=7, online=True, device_status=1, warning_mask=0, fault_mask=0, bowl_weight=1, schedule=[self.meal('06:50:00',6,True),self.meal('21:00:00',5,False)])
    def meal(self, at, portions, done):
        return dict(feedingTime=at, portions=portions, planFinishStatus=done, status=True, repeatType=1, supperFlag=0, expireStatus=False)
    def run_plan(self):
        return mod.plan(self.data,self.opts,self.now)
    def test_real_example(self):
        r=self.run_plan(); self.assertEqual(r['forecast'],108); self.assertEqual(r['suggested_portions'],0)
    def test_complement(self):
        self.opts['portion_weight']=7
        r=self.run_plan(); self.assertEqual(r['budget'],16); self.assertEqual(r['suggested_portions'],2)
    def test_no_schedule(self):
        self.data['schedule']=None; self.assertEqual(self.run_plan()['decision'],'unavailable')
    def test_bowl(self):
        self.opts['portion_weight']=7; self.data['bowl_weight']=10; self.assertEqual(self.run_plan()['suggested_portions'],0)
    def test_fault(self):
        self.opts['portion_weight']=7; self.data['fault_mask']=1; self.assertEqual(self.run_plan()['decision'],'device_not_ready')
    def test_soon(self):
        self.opts['portion_weight']=7; self.data['schedule'][1]['feedingTime']='10:00:00'; self.assertEqual(self.run_plan()['decision'],'meal_soon')
    def test_overdue(self):
        self.data['schedule'][1]['feedingTime']='09:00:00'; self.assertEqual(self.run_plan()['decision'],'schedule_uncertain')
    def test_unknown_repeat(self):
        self.data['schedule'][1]['repeatType']=2; self.assertEqual(self.run_plan()['decision'],'unavailable')
    def test_count_inconsistent(self):
        self.data['portions_today']=0; self.assertEqual(self.run_plan()['decision'],'schedule_uncertain')
    def test_missing_fault(self):
        self.opts['portion_weight']=7; self.data.pop('fault_mask'); self.assertEqual(self.run_plan()['decision'],'device_not_ready')
    def test_missing_counter(self):
        self.data.pop('portions_today'); self.assertIsNone(self.run_plan()['forecast'])
    def test_limit(self):
        self.opts['target']=200; self.assertEqual(self.run_plan()['suggested_portions'],3)

if __name__=='__main__': unittest.main()
