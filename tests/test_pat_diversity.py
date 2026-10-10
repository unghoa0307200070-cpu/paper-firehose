import importlib.util
import sys
import unittest
from pathlib import Path
import feedparser
import yaml
from paper_firehose.processors.relevance import RelevancePolicy


class PATDiversityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(cls.root/'scripts'))
        from build_digest import select_rows
        from prepare_feeds import europepmc_rss
        cls.select_rows = staticmethod(select_rows)
        cls.europepmc_rss = staticmethod(europepmc_rss)
        topic = yaml.safe_load((cls.root/'github_actions_config/topics/perovskites.yaml').read_text(encoding='utf-8'))
        cls.policy = RelevancePolicy(topic['relevance'])

    def test_accepts_acoustics_and_new_measurement_interests(self):
        for title in [
            'Particle image velocimetry for flow field measurement in mixing processes',
            'Embodied multimodal perception and reinforcement learning for robot manipulation',
            'Ultrasonic imaging modalities enabled by laser diffuse ultrasonic phased arrays',
        ]:
            with self.subTest(title=title):
                self.assertIsNotNone(self.policy.evaluate({'title':title}))
        self.assertIsNone(self.policy.evaluate({'title':'Electromagnetic vibration energy harvester with displacement amplification mechanism'}))

    def test_spectral_volume_does_not_hide_computational_methods_and_vision(self):
        titles = ['In-line Raman PAT spectroscopy for pharmaceutical tablet quality monitoring']
        titles += [f'Calibration transfer in near-infrared spectroscopy method {i}' for i in range(20)]
        titles += ['Embodied multimodal perception and reinforcement learning for robot manipulation',
                   'Vibration and acoustic sensor fusion for equipment condition monitoring',
                   'Camera image analysis for industrial quality monitoring']
        rows=[{'id':str(i),'title':title,'link':'https://example.com/'+str(i),'rank_score':1-i/100} for i,title in enumerate(titles)]
        rows=[row for row in rows if self.policy.evaluate(row)]
        rows.sort(key=lambda row:(self.policy.evaluate(row)['priority'],row['rank_score']),reverse=True)
        chosen=self.select_rows(rows,self.policy)
        titles=[row['title'] for row in chosen]
        self.assertIn('Embodied multimodal perception and reinforcement learning for robot manipulation',titles)
        self.assertIn('Camera image analysis for industrial quality monitoring',titles)
        self.assertLessEqual(sum('Calibration transfer' in title for title in titles),4)
        self.assertIn('pharmaceutical',chosen[0]['title'])
        self.assertEqual(len({row['id'] for row in chosen}),len(chosen))

    def test_empty_search_is_valid_and_abstracts_are_preserved(self):
        class Response:
            def __init__(self,papers):self.papers=papers
            def raise_for_status(self):pass
            def json(self):return {'hitCount':len(self.papers),'resultList':{'result':self.papers}}
        source={'name':'PAT','url':'https://example.com/search','query':'PAT'}
        payload,hits=self.europepmc_rss(source,get=lambda *a,**kw:Response([]))
        self.assertEqual(hits,0)
        self.assertEqual(len(feedparser.parse(payload).entries),0)
        paper={'title':'Granulation PAT','doi':'10.1234/test','firstPublicationDate':'2026-10-01','abstractText':'Raman and vibration monitoring'}
        payload,hits=self.europepmc_rss(source,get=lambda *a,**kw:Response([paper]))
        entry=feedparser.parse(payload).entries[0]
        self.assertIn('vibration',entry.summary)
        self.assertEqual(entry.link,'https://doi.org/10.1234/test')
        self.assertEqual(entry.published_parsed.tm_year,2026)


if __name__=='__main__':
    unittest.main()

