"""
migrate_add_session_id.py

Fixes:
    sqlite3.OperationalError: no such column: attendee.session_id

Why this happens: db.create_all() (used at Flask startup) only creates
tables that don't exist yet — it never adds a new column to a table
that's already there. Your `attendee` table already exists with real
data in it, so a plain restart of app.py does NOT pick up the new
session_id column that was added to the Attendee model.

This script adds ONLY that one column, in place, on your existing
`attendee` table. It does not touch `venue`, `speaker`, `session`, or
any existing rows in `attendee` — every attendee you already have
keeps their id, fullname, email, phone, status, etc. exactly as they
are. Existing attendees will simply have session_id = NULL, since
they registered before session selection existed.

Run this ONCE, before starting the app again:
    python migrate_add_session_id.py

Safe to run more than once — if the column already exists, it tells
you that instead of erroring out or duplicating anything.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import app
from models import db


with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE attendee ADD COLUMN session_id INTEGER"
            ))
            conn.commit()
        print("Success: 'session_id' column added to the attendee table.")
    except OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("No change made: 'session_id' column already exists.")
        else:
            raise