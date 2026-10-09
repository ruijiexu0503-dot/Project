import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_vldocir import evaluate, metrics


class EvaluationTests(unittest.TestCase):
    def test_partial_evidence_not_complete(self):
        m=metrics([('d','1')],{('d','1'),('d','2')},3)
        self.assertEqual(m['Recall@3'],.5)
        self.assertEqual(m['RecallAll@3'],0)
        self.assertEqual(m['nDCGAll@3'],0)

    def test_duplicates_do_not_consume_page_budget(self):
        m=metrics([('d','1'),('d','1'),('d','2')],{('d','1'),('d','2')},2)
        self.assertEqual(m['nDCG@2'],1)

    def test_node_mapping_and_missing_query(self):
        q=[{'question_id':str(i),'question_type':'single-page_single-evidence'} for i in range(2)]
        e=[{'question_id':str(i),'document_id':'d','page_number':1} for i in range(2)]
        r=evaluate(q,e,[{'question_id':'0','node_id':'n','score':1}],{'n':[('d','1')]})
        self.assertEqual(r['micro']['Recall@3'],.5)
        self.assertEqual(r['queries_without_results'],1)
        self.assertIsNone(r['macro_six_types'])

    def test_gold_missing_from_corpus_rejected(self):
        q=[{'question_id':'q','question_type':'single-page_single-evidence'}]
        e=[{'question_id':'q','document_id':'d','page_number':1}]
        with self.assertRaises(ValueError): evaluate(q,e,[],corpus={('d','2')})


if __name__=='__main__': unittest.main()
