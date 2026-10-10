"""Download RSS with bounded timeouts and report unavailable sources."""
import concurrent.futures
import json
import os
import datetime as dt
import email.utils
import xml.etree.ElementTree as ET
from pathlib import Path
import feedparser
import requests
import yaml
from academic_sources import openalex_rss, conference_rss


def europepmc_rss(value, days=180, get=requests.get):
    """Adapt bounded, date-filtered Europe PMC metadata to the RSS pipeline."""
    today = dt.datetime.now(dt.timezone.utc).date()
    since = today - dt.timedelta(days=days)
    query = f'({value["query"]}) AND FIRST_PDATE:[{since} TO {today}] sort_date:y'
    response = get(value['url'], params={'query':query, 'format':'json',
                   'resultType':'core', 'pageSize':1000}, timeout=(10,30))
    response.raise_for_status()
    result = response.json()
    if 'resultList' not in result or 'hitCount' not in result:
        raise ValueError('Europe PMC returned an unexpected search response')
    papers = result.get('resultList', {}).get('result', [])
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = value['name']
    ET.SubElement(channel, 'link').text = 'https://europepmc.org/'
    ET.SubElement(channel, 'description').text = value['query']
    for paper in papers:
        if not paper.get('title'):
            continue
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = paper['title']
        link = ('https://doi.org/' + paper['doi'] if paper.get('doi') else
                'https://europepmc.org/article/' + paper['source'] + '/' + paper['id'])
        ET.SubElement(item, 'link').text = link
        ET.SubElement(item, 'guid').text = link
        ET.SubElement(item, 'description').text = paper.get('abstractText') or ''
        ET.SubElement(item, 'author').text = paper.get('authorString') or ''
        if paper.get('firstPublicationDate'):
            date = dt.datetime.fromisoformat(paper['firstPublicationDate']).replace(tzinfo=dt.timezone.utc)
            ET.SubElement(item, 'pubDate').text = email.utils.format_datetime(date)
    return ET.tostring(rss, encoding='utf-8', xml_declaration=True), int(result.get('hitCount',0))


def main():
    config_path = Path(os.environ["CONFIG_PATH"])
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = Path(os.environ["PAPER_FIREHOSE_DATA_DIR"])
    cache = data / "feeds"
    cache.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        key, value = item
        try:
            kind = value.get('kind')
            is_search = kind in ('europepmc','openalex','cvf','pmlr')
            details = {}
            if kind == 'openalex':
                content, details = openalex_rss(value,int(cfg.get('defaults', {}).get('time_window_days',180)))
            elif kind in ('cvf','pmlr'):
                content, details = conference_rss(value,int(cfg.get('defaults', {}).get('time_window_days',180)),cache=data/'source-cache')
            elif kind == 'europepmc':
                content, hits = europepmc_rss(value, int(cfg.get('defaults', {}).get('time_window_days',180)))
            else:
                response = requests.get(value["url"],timeout=(10,30),
                    headers={"User-Agent":"PaperFirehose/0.4 research RSS reader"})
                response.raise_for_status()
                content = response.content
            feed = feedparser.parse(content)
            if not feed.entries and not is_search:
                raise ValueError("The source returned no parseable paper entries")
            path = cache / (key + ".xml")
            path.write_bytes(content)
            result = {"key":key,"name":value["name"],"entries":len(feed.entries),"path":str(path.resolve())}
            result.update(details)
            if kind == 'europepmc':
                result.update(search_hits=hits, truncated=hits>len(feed.entries))
            return result
        except Exception as exc:
            return {"key":key,"name":value["name"],"error":str(exc)[:300]}
    enabled = [(key,value) for key,value in cfg["feeds"].items() if value.get("enabled",True)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch,enabled))
    (data / "feed-status.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    successful = [row for row in results if not row.get("error")]
    for row in results:
        if row.get("error"):
            cfg["feeds"][row["key"]]["enabled"] = False
        else:
            cfg["feeds"][row["key"]]["url"] = row["path"]
        print(json.dumps(row,ensure_ascii=False),flush=True)
    if not successful:
        raise RuntimeError("No RSS source could be read; keep the previous published digest.")
    config_path.write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),encoding="utf-8")


if __name__ == "__main__":
    main()



