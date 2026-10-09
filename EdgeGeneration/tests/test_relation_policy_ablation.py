import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_relation_policy_ablation import SIGNALS, validate


class PerLabelValidationTests(unittest.TestCase):
    def setUp(self):
        self.task={'task_id':'x','evidence_a':{'text':'Observed 90 pulses.'},'evidence_b':{'text':'Efficiency was 90 percent.'}}
        self.value={'task_id':'x','checks':[{'signal':s,'decision':'REJECT','direction':'NONE','anchor_a':None,'anchor_b':None,'reason':'Different scope.'} for s in sorted(SIGNALS)]}

    def test_all_labels_required(self):
        self.assertTrue(validate(self.value,self.task))
        self.value['checks'].pop()
        self.assertFalse(validate(self.value,self.task))

    def test_multiple_accepted_labels(self):
        for c in self.value['checks'][:2]:
            c.update(decision='ACCEPT',direction='A_TO_B',anchor_a='90 pulses',anchor_b='90 percent')
        self.assertTrue(validate(self.value,self.task))
        self.value['checks'][0]['anchor_a']='invented observation'
        self.assertFalse(validate(self.value,self.task))

    def test_wrong_id_rejected(self):
        self.value['task_id']='other'
        self.assertFalse(validate(self.value,self.task))

    def test_uncertain_is_not_reject(self):
        self.value['checks'][0]['decision']='UNCERTAIN'
        self.assertFalse(validate(self.value,self.task))
