import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
import yaml
from paper_firehose.processors.relevance import RelevancePolicy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from paper_dates import within_window, reading_order
from build_digest import render


class PaperRecencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        topic=yaml.safe_load((ROOT/'github_actions_config/topics/perovskites.yaml').read_text(encoding='utf-8'))
        cls.policy=RelevancePolicy(topic['relevance'])
        cls.today=dt.date(2026,10,8)

    def paper(self,age,score=0.5):
        return {'title':'In-line Raman PAT spectroscopy for pharmaceutical tablet quality monitoring',
                'published_date':str(self.today-dt.timedelta(days=age)),'rank_score':score}

    def test_half_year_boundary_and_unknown_date(self):
        self.assertTrue(within_window(self.paper(180),180,self.today))
        self.assertFalse(within_window(self.paper(181),180,self.today))
        self.assertFalse(within_window(self.paper(-1),180,self.today))
        unknown=dict(self.paper(0),published_date=None)
        self.assertTrue(within_window(unknown,180,self.today))
        self.assertLess(reading_order(unknown,self.policy,today=self.today),reading_order(self.paper(0),self.policy,today=self.today))

    def test_freshness_breaks_close_relevance_without_overriding_large_gap(self):
        self.assertGreater(reading_order(self.paper(2),self.policy,today=self.today),reading_order(self.paper(150),self.policy,today=self.today))
        self.assertGreater(reading_order(self.paper(150,0.9),self.policy,today=self.today),reading_order(self.paper(2,0.5),self.policy,today=self.today))
        transfer={'title':'Vibration signal analysis for bearing fault diagnosis','published_date':str(self.today),'rank_score':1.0}
        self.assertGreater(reading_order(self.paper(150,0.4),self.policy,today=self.today),reading_order(transfer,self.policy,today=self.today))

    def test_current_papers_do_not_hide_half_year_archive(self):
        now=dt.datetime.now(dt.timezone.utc).date()
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)
            with closing(sqlite3.connect(data/'papers.db')) as db, db:
                db.execute('CREATE TABLE entries(id TEXT,title TEXT,published_date TEXT,rank_score REAL,link TEXT)')
                db.execute('INSERT INTO entries VALUES(?,?,?,?,?)',('new',self.paper(1)['title'],str(now-dt.timedelta(days=1)),0.5,'https://example.com/new'))
            with closing(sqlite3.connect(data/'matched_entries_history.db')) as db, db:
                db.execute('CREATE TABLE matched_entries(entry_id TEXT,title TEXT,published_date TEXT,rank_score REAL,link TEXT)')
                for key,age in [('old',90),('expired',181)]:
                    db.execute('INSERT INTO matched_entries VALUES(?,?,?,?,?)',(key,self.paper(age)['title'],str(now-dt.timedelta(days=age)),0.5,'https://example.com/'+key))
            with patch('build_digest.load_policy',return_value=self.policy):
                status=render(data,data/'site')
            page=(data/'site/index.html').read_text(encoding='utf-8')
            self.assertEqual(status['publication_window_days'],180)
            self.assertEqual(status['displayed'],2)
            self.assertLess(page.index('https://example.com/new'),page.index('https://example.com/old'))
            self.assertNotIn('https://example.com/expired',page)

    def test_ingestion_and_display_windows_agree(self):
        cfg=yaml.safe_load((ROOT/'github_actions_config/config.yaml').read_text(encoding='utf-8'))
        self.assertEqual(cfg['defaults']['time_window_days'],self.policy.config['publication_window_days'])


if __name__=='__main__':
    unittest.main()
