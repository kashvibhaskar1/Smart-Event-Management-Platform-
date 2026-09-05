"""
migrate_add_unavailable_reason.py

One-off, safe schema update: adds the new `unavailable_reason` column
to the EXISTING `venue` table.

Why this script exists:
db.create_all() (used at Flask startup) only creates tables that don't
exist yet — it does NOT add new columns to a table that's already
there. Since your `venue` table already exists with seeded data, a
plain restart of app.py will NOT pick up the new `unavailable_reason`
field on its own. This script adds just that one column, in place,
without touching any existing rows in `venue`, `venue_booking`, or
`attendee`.

Run this ONCE, before starting the app again:
    python migrate_add_unavailable_reason.py

Safe to run more than once — if the column already exists, it will
tell you that instead of erroring out or duplicating anything.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import app
from models import db

with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE venue ADD COLUMN unavailable_reason VARCHAR(255)"
            ))
            conn.commit()
        print("Success: 'unavailable_reason' column added to the venue table.")
    except OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("No change made: 'unavailable_reason' column already exists.")
        else:
            raise