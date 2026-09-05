"""
seed_events.py

Inserts three demo events used to test event-scoped sponsor filtering.
Safe to re-run — duplicate-checked by name.

Run with:
    python seed_events.py
"""

from app import app
from models import db, Event

EVENTS = [
    {
        "name": "TechConnect Summit 2026",
        "date_display": "Aug 14–15, 2026",
        "location": "Bangalore International Centre",
    },
    {
        "name": "DevDays Hyderabad 2026",
        "date_display": "Oct 10–11, 2026",
        "location": "HICC, Hyderabad",
    },
    {
        "name": "CloudConf Pune 2025",
        "date_display": "Dec 5–6, 2025",
        "location": "Pune Tech Park Auditorium",
    },
]


def seed():
    with app.app_context():
        inserted = 0
        skipped = 0
        for e in EVENTS:
            if Event.query.filter_by(name=e["name"]).first():
                skipped += 1
            else:
                db.session.add(Event(**e))
                inserted += 1
        db.session.commit()
        print(f"Events — inserted: {inserted}, skipped: {skipped}")


if __name__ == "__main__":
    seed()
