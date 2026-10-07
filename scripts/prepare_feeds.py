"""Download RSS with bounded timeouts and report unavailable sources."""
import concurrent.futures
import json
import os
from pathlib import Path
import feedparser
import requests
import yaml


def main():
    config_path = Path(os.environ["CONFIG_PATH"])
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = Path(os.environ["PAPER_FIREHOSE_DATA_DIR"])
    cache = data / "feeds"
    cache.mkdir(parents=True,exist_ok=True)
    def fetch(item):
        key, value = item
        try:
            response = requests.get(value["url"],timeout=(10,30),
                headers={"User-Agent":"PaperFirehose/0.4 research RSS reader"})
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if not feed.entries:
                raise ValueError("The source returned no parseable paper entries")
            path = cache / (key + ".xml")
            path.write_bytes(response.content)
            return {"key":key,"name":value["name"],"entries":len(feed.entries),"path":str(path.resolve())}
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
