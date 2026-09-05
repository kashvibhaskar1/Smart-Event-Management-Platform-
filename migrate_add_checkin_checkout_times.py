"""
migrate_add_checkin_checkout_times.py

Adds the check_in_time and check_out_time columns to the EXISTING
attendee table.

Same situation as the last two migrations in this project
(unavailable_reason, session_id): db.create_all() only creates tables
that don't exist yet — it never adds a new column to a table that's
already there. Since attendee already exists with real data, restarting
Flask alone will NOT pick up these two new columns, and you'll get:
    sqlite3.OperationalError: no such column: attendee.check_in_time

This script adds both columns in place. It does not touch any existing
attendee rows beyond adding the new (initially NULL) columns — nobody's
name, email, status, or session_id changes.

Run this ONCE, before starting the app again:
    python migrate_add_checkin_checkout_times.py

Safe to run more than once — columns that already exist are skipped.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import app
from models import db


def add_column_if_missing(table, column, coltype):
    try:
        with db.engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            conn.commit()
        print(f"Added column '{column}' to '{table}'.")
    except OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print(f"No change: '{table}.{column}' already exists.")
        else:
            raise


with app.app_context():
    add_column_if_missing("attendee", "check_in_time", "DATETIME")
    add_column_if_missing("attendee", "check_out_time", "DATETIME")
    print("\nMigration complete.")