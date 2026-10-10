"""Publication window and a bounded freshness preference for the reading page."""
import datetime as dt
import re


def publication_month(row):
    match=re.search(r'论文集月份：(\d{4}-\d{2})',str(row.get('summary') or ''))
    return match.group(1) if match else None


def publication_age(row, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    try:
        raw=publication_month(row) or str(row.get('published_date') or '')[:10]
        published = dt.date.fromisoformat(raw+'-01' if re.fullmatch(r'\d{4}-\d{2}',raw) else raw)
    except ValueError:
        return None
    return (today - published).days


def within_window(row, days=180, today=None):
    age = publication_age(row, today)
    # An unknown date is kept, but never awarded a freshness bonus.
    return age is None or 0 <= age <= days


def reading_order(row, policy, days=180, weight=0.1, today=None):
    age = publication_age(row, today)
    freshness = weight * (1 - age / days) if age is not None and 0 <= age <= days else 0
    return (policy.evaluate(row)['priority'], (row.get('rank_score') or 0) + freshness,
            -age if age is not None and age >= 0 else -1000000)

