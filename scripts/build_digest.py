"""Build a compact daily reading page; no LLM/API key is used."""
import datetime as dt
import html
import json
import os
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from review_candidates import load_policy
from paper_dates import within_window, reading_order


def clean(value):
    return html.escape(re.sub(r"<[^>]*>", " ", str(value or "")))


def read_rows(path, table):
    if not path.exists():
        return []
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]


def select_rows(candidates, policy, total=15):
    """Keep pharmaceutical papers first, then represent available sensing modes."""
    rows, used, seen = [], Counter(), set()
    limits = policy.config.get('display_limits', {})
    spectral_limit = int(policy.config.get('spectral_transfer_limit', total))
    spectral_only = 0
    def add(row):
        nonlocal spectral_only
        result = policy.evaluate(row)
        key = row.get('id') or row.get('entry_id') or row.get('link')
        if not result or key in seen or len(rows) >= total:
            return False
        priority = result['priority']
        modalities = set(result['modalities'])
        only_spectral = priority < 4 and '光谱' in modalities and not modalities.intersection({'振动','声学／超声','视觉'})
        if used[priority] >= int(limits.get(priority,total)) or (only_spectral and spectral_only >= spectral_limit):
            return False
        rows.append(row)
        seen.add(key)
        used[priority] += 1
        spectral_only += int(only_spectral)
        return True
    for row in candidates:
        if policy.evaluate(row)['priority'] >= 4 and len(rows) < min(8,total):
            add(row)
    # Targets apply only when actual relevant candidates exist; never invent entries.
    mode_patterns = dict(policy.modalities)
    for modality, target in policy.config.get('modality_targets', {}).items():
        regex = mode_patterns.get(modality)
        focused = [row for row in candidates if regex and regex.search(clean(row.get('title')))]
        pool = focused or [row for row in candidates if modality in policy.evaluate(row)['modalities']]
        for row in pool:
            # A broad review mentioning vibration in its abstract should not
            # displace a paper actually focused on vibration measurement.
            count = sum(bool(regex.search(clean(item.get('title')))) if focused else modality in policy.evaluate(item)['modalities'] for item in rows)
            if count >= int(target):
                break
            add(row)
    for row in candidates:
        add(row)
    return rows


def render(data, site):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    policy = load_policy()
    days = int(policy.config.get("publication_window_days",180))
    weight = float(policy.config.get("recency_weight",0.1))
    today = now.astimezone(dt.timezone.utc).date()
    current = read_rows(data / "papers.db", "entries")
    if current and not any(row.get("rank_score") is not None for row in current):
        raise RuntimeError("Matching papers exist, but semantic ranking failed.")
    history = read_rows(data / "matched_entries_history.db", "matched_entries")
    recent = [row for row in history if policy.evaluate(row) and within_window(row,days,today)]
    current = [row for row in current if policy.evaluate(row) and within_window(row,days,today)]
    # Merge fresh candidates with the available half-year archive. Current scores win.
    pool = {}
    for row in recent + current:
        key = row.get("id") or row.get("entry_id") or row.get("link")
        pool[key] = row
    candidates = sorted(pool.values(), key=lambda row:reading_order(row,policy,days,weight,today), reverse=True)
    rows = select_rows(candidates, policy)
    mode_counts = Counter(mode for row in rows for mode in policy.evaluate(row)['modalities'])
    cards = []
    for row in rows:
        link = str(row.get("link") or "")
        if not link.startswith(("https://", "http://")):
            continue
        text = clean(row.get("abstract") or row.get("summary"))
        relevance = policy.evaluate(row)
        rationale = clean(relevance["label"])
        if relevance["modalities"]:
            rationale += " · " + clean("、".join(relevance["modalities"]))
        rationale += " · 命中：" + clean("、".join(relevance["evidence"]))
        cards.append(
            '<article><h2><a target="_blank" rel="noopener noreferrer" href="'
            + html.escape(link, quote=True) + '">' + clean(row.get("title"))
            + '</a></h2><p class="meta">' + clean(row.get("feed_name"))
            + ' · 发表日期：' + clean(row.get("published_date") or "来源未提供")
            + '</p><p class="reason">入选依据：' + rationale + '</p><p>' + text + '</p></article>'
        )
    statuses_path = data / "feed-status.json"
    statuses = json.loads(statuses_path.read_text(encoding="utf-8")) if statuses_path.exists() else []
    failed = [row["name"] for row in statuses if row.get("error")]
    availability = f"本次成功读取 {len(statuses)-len(failed)}/{len(statuses)} 个来源。" if statuses else ""
    failure_text = "暂时无法读取：" + "、".join(failed) + "。" if failed else ""
    notice = ("本次没有新增匹配论文，继续推荐近半年已收录的相关文献。"
              if not current else "优先制药工程与 PAT，同时兼顾实际可获取的振动、视觉、声学与融合方法；最多 15 篇，不足时不补齐。")
    if not cards:
        cards = ['<article>目前没有可推荐的候选论文。历史记录可从下方入口查看。</article>']
    content = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>多模态制药过程 PAT · 每日文献</title>
<style>body{font:16px/1.75 system-ui,sans-serif;background:#f4f6f8;color:#233247;margin:0}
main{max-width:1000px;margin:auto;padding:32px 20px}h1{font-size:30px}h2{font-size:20px}
article,.notice{background:white;padding:22px 26px;margin:18px 0;border-radius:12px}
a{color:#165baf;text-decoration:none}a:hover{text-decoration:underline}
.meta,footer{color:#607084;font-size:14px}.reason{color:#245d50;font-size:14px}p{overflow-wrap:anywhere}</style><main>
<h1>多模态制药过程 PAT · 每日文献</h1>
<p>机器视觉 · Raman／近红外／高光谱 · 振动与声学 · 传感器融合 · 软测量与过程质量</p>
<p class="meta">更新于：UPDATE（北京时间） · 本次新增 NEW 篇 · 近半年已收录 RECENT 篇</p>
<p class="meta">文献范围：近 WINDOW 天（约半年）；同类论文相关性相近时优先较新的研究。</p>
<p class="meta">本页检测模态（同一论文可计入多项）：MODES</p>
<div class="notice">NOTICE<br>AVAILABILITY FAILURE<br>来源范围以可获取的订阅条目和检索记录为准，并非近半年的全部文献。<br>优先制药与制剂过程检测，其次是可迁移的过程融合、光谱建模和环境适应方法。单项检测技术也可入选；入选依据为规则命中，不代表适用性已经验证。arXiv 来源包含预印本。</div>
CARDS<footer><a href="results_pharma_vision_ranked.html">查看本次全部候选（按相关性）</a> ·
<a href="history_viewer_cards.html">查看历史文献</a><p>每天计划于北京时间 09:00 更新，实际运行可能延迟。显示论文原文摘要，不调用付费 AI 摘要接口。</p></footer></main></html>"""
    replacements = {"WINDOW":str(days),"MODES":clean(" · ".join(f"{mode} {mode_counts.get(mode,0)} 篇" for mode in ['振动','声学／超声','视觉','光谱','融合'])),"UPDATE":now.strftime("%Y-%m-%d %H:%M"),"NEW":str(len(current)),
                    "RECENT":str(len(recent)), "NOTICE":notice,"AVAILABILITY":availability,
                    "FAILURE":clean(failure_text),"CARDS":"".join(cards)}
    for key, value in replacements.items():
        content = content.replace(key, value)
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(content,encoding="utf-8")
    result = {"profile":"pharma-pat-halfyear-v3","publication_window_days":days,"recency_weight":weight,"modalities":dict(mode_counts),"pharma_process_displayed":sum(policy.evaluate(row)['priority']>=4 for row in rows),"new_matches":len(current),"recent_matches":len(recent),"displayed":len(rows),
              "sources":len(statuses),"failed_sources":failed}
    (site / "digest-status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


if __name__ == "__main__":
    render(Path(os.environ["PAPER_FIREHOSE_DATA_DIR"]), Path("site"))



