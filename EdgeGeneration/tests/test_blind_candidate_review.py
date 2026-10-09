import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_blind_candidate_review as b
import score_blind_candidate_review as s


class BlindReviewTests(unittest.TestCase):
    def arms(self):
        def row(a,z):return {'source_unit_id':a,'target_unit_id':z,'scope':'cross_document','score':.7}
        return {'lexical':[row('A','B'),row('A','C')],
                'dense':[row('A','B'),row('A','D')], 'hybrid':[row('A','B'),row('A','E')]}

    def test_union_probability_deduplication_and_reproducibility(self):
        arms=self.arms()
        plan,lanes=b.sample_plan(arms,1,123)
        self.assertEqual((plan,lanes),b.sample_plan(arms,1,123))
        self.assertEqual(len(plan),len({tuple(sorted((r['unit_a'],r['unit_b']))) for r in plan}))
        for r in plan:
            self.assertAlmostEqual(r['inclusion_probability'],1-.5**len(r['arm_membership']))
        arms['dense'].pop()
        with self.assertRaises(ValueError):b.sample_plan(arms,1,123)

    def test_complete_census_matches_arm_yields_and_incomplete_has_no_scores(self):
        plan,lanes=b.sample_plan(self.arms(),2,123)
        labels=[]
        for r in plan:
            yes=set((r['unit_a'],r['unit_b']))=={'A','B'}
            labels.append({'task_id':r['task_id'],'package_id':'test','relation_exists':'YES' if yes else 'NO',
                'reviewer':'synthetic_test_fixture','review_method':'model_only','basis':'test only',
                'evidence_a':'source a','evidence_b':'source b',
                'relations':[{'type':'SUPPORTS','direction':'A_TO_B'}] if yes else []})
        manifest={'tasks_sha256':'test','lanes':lanes,'arm_population':{a:2 for a in b.ARMS}}
        result=s.score(plan,labels,manifest)
        for arm in b.ARMS:self.assertEqual(result['metrics'][arm]['all']['estimated_confirmed_fraction'],.5)
        labels[0]['relation_exists']=None
        self.assertNotIn('metrics',s.score(plan,labels,manifest))
        labels[0]['package_id']='other'
        with self.assertRaises(ValueError):s.score(plan,labels,manifest)

    def test_evidence_and_direction_required(self):
        plan,lanes=b.sample_plan(self.arms(),2,123)
        manifest={'tasks_sha256':'test','lanes':lanes,'arm_population':{a:2 for a in b.ARMS}}
        labels=[{'task_id':r['task_id'],'package_id':'test','relation_exists':None} for r in plan]
        labels[0].update(relation_exists='YES',reviewer='test',review_method='model_only',basis='test',
                         relations=[{'type':'SUPPORTS','direction':'UNRESOLVED'}],evidence_a='a',evidence_b='b')
        with self.assertRaises(ValueError):s.score(plan,labels,manifest)
        labels[0]['relations'][0]['direction']='A_TO_B';labels[0]['evidence_b']=''
        with self.assertRaises(ValueError):s.score(plan,labels,manifest)

    def test_public_package_excludes_retrieval_metadata_and_escapes_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c=root/'c';snapshot=root/'snapshot';c.mkdir();snapshot.mkdir()
            for arm,rows in self.arms().items():b.write(c/f'{arm}_budget_candidates.jsonl',rows)
            units=[{'unit_id':u,'doc_id':u,'page_ids':['page_1'],'text':'Untrusted </script><script>attack()',
                    'description_source':'source_text','source_fragment_ids':[],'source_visual_ids':[]} for u in 'ABCDE']
            b.write(snapshot/'units.jsonl',units)
            b.build(c,snapshot,root/'out',2,123)
            tasks=b.read(root/'out/reviewer/tasks.jsonl')
            def keys(value):
                if isinstance(value,dict):return set(value)|set().union(*(keys(v) for v in value.values()))
                if isinstance(value,list):return set().union(*(keys(v) for v in value))
                return set()
            self.assertFalse(keys(tasks)&{'score','arm_membership','inclusion_probability','retrieval_route','rank_in_file'})
            html=(root/'out/reviewer/index.html').read_text()
            self.assertNotIn('Untrusted </script>',html)
            labels=b.read(root/'out/reviewer/labels_template.jsonl')
            self.assertTrue(all(r['relation_exists'] is None and r['package_id'] for r in labels))


if __name__=='__main__':unittest.main()
