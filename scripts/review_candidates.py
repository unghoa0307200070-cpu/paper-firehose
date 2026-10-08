"""Recheck fetched abstracts and filter only the public history copies."""
import argparse
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
import yaml
from paper_firehose.processors.relevance import RelevancePolicy
from paper_dates import within_window


def load_policy():
    config = Path(os.environ['CONFIG_PATH'])
    topics = list((config.parent / 'topics').glob('*.yaml'))
    if len(topics) != 1:
        raise ValueError('This project review expects one recommendation topic')
    topic = yaml.safe_load(topics[0].read_text(encoding='utf-8'))
    return RelevancePolicy(topic.get('relevance'))


def review(path, table, key, policy):
    if not path.exists():
        return {'before':0,'retained':0,'rejected':0,'categories':{}}
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory=sqlite3.Row
        rows=[dict(row) for row in db.execute(f'SELECT * FROM {table}')]
        rejected=[]
        groups=Counter()
        for row in rows:
            result=policy.evaluate(row)
            if result and within_window(row,int(policy.config.get("publication_window_days",180))):
                groups[result['label']]+=1
            else:
                rejected.append((row[key],))
        db.executemany(f'DELETE FROM {table} WHERE {key} = ?',rejected)
    return {'before':len(rows),'retained':len(rows)-len(rejected),'rejected':len(rejected),'categories':dict(groups)}


def main(site=None):
    policy=load_policy()
    data=Path(os.environ['PAPER_FIREHOSE_DATA_DIR'])
    if site:
        # The full runtime history remains intact. Only published copies are filtered.
        for name in ('matched_entries_history.db','matched_entries_history.recent.db'):
            print(json.dumps(review(Path(site)/name,'matched_entries','entry_id',policy),ensure_ascii=False))
        return
    result=review(data/'papers.db','entries','id',policy)
    (data/'relevance-status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--site')
    main(parser.parse_args().site)
