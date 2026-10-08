"""Publication window and a bounded freshness preference for the reading page."""
import datetime as dt


def publication_age(row, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    try:
        published = dt.date.fromisoformat(str(row.get('published_date') or '')[:10])
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
