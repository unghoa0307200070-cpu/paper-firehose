"""Bounded adapters for official conference papers and indexed journal methods."""
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin
import requests
import threading
import time

_journal_lock=threading.Lock()


def journal_request(url,params,get):
    """Serialize public metadata requests and honor short server backoffs."""
    for attempt in range(3):
        with _journal_lock:
            response=get(url,params=params,timeout=(10,30))
            time.sleep(1)
        if getattr(response,'status_code',200) not in (429,502,503,504):
            response.raise_for_status()
            return response
        if attempt==2:response.raise_for_status()
        delay=getattr(response,'headers',{}).get('Retry-After','')
        time.sleep(min(20,float(delay)) if str(delay).isdigit() else 3*(attempt+1))


def crossref_rss(source,days=180,get=requests.get):
    today=dt.datetime.now(dt.timezone.utc).date();since=today-dt.timedelta(days=days)
    params={'filter':f'issn:{source["issn"]},from-pub-date:{since},until-pub-date:{today}',
            'rows':200,'sort':'published','order':'desc'}
    response=journal_request('https://api.crossref.org/works',params,get)
    message=response.json().get('message') or {}
    if 'items' not in message:raise ValueError('Unexpected Crossref response')
    papers=[]
    for work in message['items']:
        dates=[]
        for field in ('published-online','published-print','published'):
            parts=(work.get(field)or{}).get('date-parts',[[]])[0]
            if len(parts)==3:dates.append(dt.date(*parts))
        if not dates:continue
        date=min(dates)
        if not since<=date<=today:continue
        papers.append({'title':' '.join(work.get('title',[])),'link':'https://doi.org/'+work['DOI'],
            'date':str(date),'description':work.get('abstract') or '',
            'author':', '.join((x.get('given','')+' '+x.get('family','')).strip() for x in work.get('author',[]))})
    return rss(source,papers),{'search_hits':message['total-results'],'provider':'Crossref fallback',
                             'truncated':message['total-results']>len(message['items'])}


def text(value):
    return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',value or ''))).strip()


def rss(source, papers):
    root=ET.Element('rss',version='2.0');channel=ET.SubElement(root,'channel')
    for key,value in [('title',source['name']),('link',source['url']),('description','Relevant computational research methods')]:
        ET.SubElement(channel,key).text=value
    for paper in papers:
        item=ET.SubElement(channel,'item')
        for key in ('title','link','description','author'):
            ET.SubElement(item,key).text=paper.get(key,'')
        ET.SubElement(item,'guid').text=paper['link']
        date=dt.datetime.fromisoformat(paper['date']).replace(tzinfo=dt.timezone.utc)
        ET.SubElement(item,'pubDate').text=email.utils.format_datetime(date)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def inverted_abstract(index):
    return ' '.join(word for _,word in sorted((position,word) for word,positions in (index or {}).items() for position in positions))


def openalex_rss(source,days=180,get=requests.get):
    today=dt.datetime.now(dt.timezone.utc).date();since=today-dt.timedelta(days=days)
    params={'filter':f'primary_location.source.id:{source["source_id"]},from_publication_date:{since},to_publication_date:{today}',
            'search':source['query'],'per_page':200,'sort':'publication_date:desc'}
    try:
        response=journal_request(source['url'],params,get)
    except requests.RequestException:
        if source.get('issn'):return crossref_rss(source,days,get)
        raise
    result=response.json()
    if 'results' not in result or 'meta' not in result:raise ValueError('Unexpected journal index response')
    papers=[]
    for work in result['results']:
        location=work.get('primary_location') or {};venue=location.get('source') or {}
        # Confirm the actual journal; never classify a preprint as an accepted paper.
        if str(venue.get('id','')).split('/')[-1]!=source['source_id']:continue
        link=work.get('doi') or location.get('landing_page_url') or work['id']
        if not link.startswith(('https://','http://')):continue
        date=work.get('publication_date')
        if not date or not since <= dt.date.fromisoformat(date) <=today:continue
        papers.append({'title':work.get('display_name') or work.get('title') or '',
            'link':link,'date':date,'description':inverted_abstract(work.get('abstract_inverted_index')),
            'author':', '.join((a.get('author')or{}).get('display_name','') for a in work.get('authorships',[]))})
    return rss(source,papers),{'search_hits':result['meta']['count'],'truncated':result['meta']['count']>len(papers)}


def select_links(candidates, groups, limit=32):
    selected=[];seen=set()
    for pattern in groups:
        regex=re.compile(pattern,re.I);count=0
        for title,link in candidates:
            if link in seen or not regex.search(title):continue
            selected.append((title,link));seen.add(link);count+=1
            if count>=8 or len(selected)>=limit:break
        if len(selected)>=limit:break
    return selected


def metadata(page):
    values={}
    for tag in re.findall(r'<meta\b[^>]*>',page,re.I):
        attrs={key:value for key,quote,value in re.findall(r'(\w+)\s*=\s*(["\'])(.*?)\2',tag,re.S)}
        if attrs.get('name','').startswith('citation_'):
            values.setdefault(attrs['name'],[]).append(html.unescape(attrs.get('content','')))
    return values


def paper_record(title,link,page,fallback_month=None):
    meta=metadata(page)
    abstract=re.search(r'<div[^>]+(?:id|class)=["\']abstract["\'][^>]*>(.*?)</div>',page,re.S|re.I)
    raw_date=(meta.get('citation_publication_date') or [''])[0].replace('/','-')
    month=None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw_date):date=raw_date
    elif fallback_month:
        # CVF supplies a year and BibTeX month, not an exact day.
        bib_month=re.search(r'month\s*=\s*\{(\w+)\}',page)
        year=int(raw_date[:4])
        month_number=list(__import__('calendar').month_name).index(bib_month.group(1)) if bib_month else fallback_month
        month=f'{year}-{month_number:02d}';date=month+'-01'
    else:raise ValueError('Conference paper lacks a reliable publication date')
    description=html.escape(text(abstract.group(1))) if abstract else ''
    if month:description=f'<p>论文集月份：{month}（来源未提供具体日期）</p>'+description
    return {'title':(meta.get('citation_title') or [title])[0],'link':link,'date':date,
            'description':description,'author':', '.join(meta.get('citation_author',[]))}


def conference_rss(source,days=180,get=requests.get,cache=None):
    today=dt.datetime.now(dt.timezone.utc).date();since=today-dt.timedelta(days=days)
    candidates=[]
    if source['kind']=='cvf':
        for year in range(since.year,today.year+1):
            month=dt.date(year,int(source.get('month',6)),1)
            if not since.replace(day=1)<=month<=today:continue
            url=source['url'].format(year=year)
            response=get(url,timeout=(10,30));response.raise_for_status()
            items=re.findall(r'<dt class="ptitle">(.*?)</dt>',response.text,re.S)
            if not items:raise ValueError('Official conference listing contains no paper titles')
            for item in items:
                match=re.search(r'<a href="([^"]+)">(.*?)</a>',item,re.S)
                if match:candidates.append((text(match.group(2)),urljoin(url,match.group(1))))
    else:
        response=get(source['url'],timeout=(10,30));response.raise_for_status()
        volumes=re.findall(r'<li><a href="(v\d+)"><b>Volume \d+</b></a>\s*Proceedings of ICML (\d{4})</li>',response.text)
        if not volumes:raise ValueError('PMLR index contains no ICML volumes')
        for volume,year in volumes:
            if int(year)<since.year or int(year)>today.year:continue
            url=urljoin(source['url'],volume+'/')
            response=get(url,timeout=(10,30));response.raise_for_status()
            blocks=re.findall(r'<div class="paper">(.*?)</div>',response.text,re.S)
            if not blocks:raise ValueError('ICML volume contains no paper entries')
            for block in blocks:
                title=re.search(r'<p class="title">(.*?)</p>',block,re.S)
                link=re.search(r'<a href="([^"]+)">abs</a>',block)
                if title and link:candidates.append((text(title.group(1)),urljoin(url,link.group(1))))
    selected=select_links(candidates,source['title_groups'],int(source.get('max_papers',32)))
    def fetch(candidate):
        title,link=candidate
        try:
            path=Path(cache)/ (hashlib.sha256(link.encode()).hexdigest()+'.json') if cache else None
            if path and path.exists():record=json.loads(path.read_text(encoding='utf-8'))
            else:
                response=get(link,timeout=(10,30));response.raise_for_status()
                record=paper_record(title,link,response.text,6 if source['kind']=='cvf' else None)
                if path:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
            if since<=dt.date.fromisoformat(record['date'])<=today:return record
            return None
        except Exception as exc:return {'error':str(exc)[:180],'link':link}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,selected))
    papers=[x for x in results if x and not x.get('error')]
    errors=[x for x in results if x and x.get('error')]
    if selected and not papers and len(errors)==len(selected):raise ValueError('No selected official conference paper could be read')
    return rss(source,papers),{'listed_papers':len(candidates),'selected_papers':len(selected),'paper_fetch_failures':len(errors),'selection_cap':int(source.get('max_papers',32))}
