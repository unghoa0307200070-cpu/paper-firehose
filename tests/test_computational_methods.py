import datetime as dt
import sys,unittest
from pathlib import Path
import feedparser,yaml
import requests
from unittest.mock import patch
from paper_firehose.processors.relevance import RelevancePolicy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from academic_sources import openalex_rss, paper_record, rss
from build_digest import select_rows
from paper_dates import publication_age,publication_month


class ComputationalMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.topic=yaml.safe_load((ROOT/'github_actions_config/topics/perovskites.yaml').read_text(encoding='utf-8'))
        cls.policy=RelevancePolicy(cls.topic['relevance'])

    def test_new_interests_and_removed_standalone_preferences(self):
        for title in ['Machine vision and deep learning for industrial defect detection',
            'Embodied multimodal perception and reinforcement learning for robot manipulation',
            'Particle image velocimetry for flow field measurement',
            'Deep reinforcement learning for chemical process control',
            'Self-supervised multimodal representation learning with missing modalities',
            'Causal discovery for time series with endogenous context variables']:
            with self.subTest(title=title):self.assertIsNotNone(self.policy.evaluate({'title':title}))
        self.assertIsNone(self.policy.evaluate({'title':'Vibration signal analysis for bearing fault diagnosis'}))
        self.assertIsNone(self.policy.evaluate({'title':'Near-infrared calibration transfer'}))
        self.assertIsNotNone(self.policy.evaluate({'title':'Process analytical technology for granulation with near-infrared and vibration sensor fusion'}))
        self.assertNotIn('振动',self.policy.config['modalities'])
        self.assertNotIn('振动',self.policy.config['modality_targets'])
        self.assertNotIn('near.infrared',self.topic['filter']['pattern'])
        self.assertNotIn('vibration',self.topic['ranking']['query'])

    def test_methods_have_space_when_many_pharma_papers_exist(self):
        rows=[{'id':str(i),'title':'Process analytical technology for pharmaceutical tablet manufacturing quality monitoring','rank_score':.8,'link':'https://example.com/'+str(i)} for i in range(20)]
        for i in range(3):rows.append({'id':'cs'+str(i),'title':'Self-supervised multimodal representation learning with missing modalities','rank_score':.3,'link':'https://example.com/cs'+str(i),'feed_name':'IEEE TPAMI'})
        chosen=select_rows(rows,self.policy)
        self.assertEqual(len(chosen),15)
        self.assertEqual(sum(row['id'].startswith('cs') for row in chosen),3)
        self.assertIn('pharmaceutical',chosen[0]['title'])

    def test_journal_adapter_preserves_abstract_and_verifies_source(self):
        today=str(dt.datetime.now(dt.timezone.utc).date())
        source={'name':'IEEE TPAMI','url':'https://example.com/works','source_id':'S199944782','query':'multimodal'}
        work={'id':'https://openalex.org/W1','title':'Multimodal sensor fusion','doi':'https://doi.org/10.1234/test',
              'publication_date':today,'primary_location':{'source':{'id':'https://openalex.org/S199944782'}},
              'abstract_inverted_index':{'Sensor':[0],'fusion':[1],'methods':[2]},'authorships':[]}
        wrong=dict(work,primary_location={'source':{'id':'https://openalex.org/Sarxiv'}})
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'meta':{'count':2},'results':[work,wrong]}
        payload,stats=openalex_rss(source,get=lambda *a,**k:Response())
        entries=feedparser.parse(payload).entries
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0].summary,'Sensor fusion methods')
        self.assertTrue(stats['truncated'])

    def test_conference_month_is_not_presented_as_an_exact_day(self):
        page='<meta name="citation_title" content="Multimodal learning"><meta name="citation_publication_date" content="2026"><div id="abstract">Sensor fusion methods</div><div>month = {June}</div>'
        record=paper_record('fallback','https://example.com/cvpr',page,6)
        entry=feedparser.parse(rss({'name':'CVPR','url':'https://example.com/'},[record])).entries[0]
        row={'summary':entry.summary,'published_date':'2026-06-01'}
        self.assertEqual(publication_month(row),'2026-06')
        self.assertIn('未提供具体日期',entry.summary)
        self.assertEqual(publication_age(row,dt.date(2026,6,8)),7)

    def test_rate_limited_journal_can_use_crossref(self):
        today=dt.datetime.now(dt.timezone.utc).date()
        source={'name':'IEEE TPAMI','url':'https://api.openalex.org/works','source_id':'S199944782','query':'multimodal','issn':'0162-8828'}
        class Response:
            def __init__(self,limited):self.status_code=429 if limited else 200;self.headers={}
            def raise_for_status(self):
                if self.status_code==429:raise requests.HTTPError('limited')
            def json(self):return {'message':{'total-results':1,'items':[{'DOI':'10.1234/test','title':['Multimodal sensor fusion'],'published-online':{'date-parts':[[today.year,today.month,today.day]]},'abstract':'Deep learning for process monitoring'}]}}
        def get(url,**kw):return Response('openalex' in url)
        with patch('academic_sources.time.sleep'):
            payload,stats=openalex_rss(source,get=get)
        self.assertEqual(len(feedparser.parse(payload).entries),1)
        self.assertEqual(stats['provider'],'Crossref fallback')


if __name__=='__main__':unittest.main()
