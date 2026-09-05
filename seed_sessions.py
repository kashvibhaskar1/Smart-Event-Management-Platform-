"""
seed_sessions.py

Inserts 10 realistic demo sessions into the existing SQLite database,
for testing Session Management, conflict detection, and Speaker
Recommendation.

All sessions are assigned to "TechConnect Summit 2026" (the event whose
dates match the session dates). Existing sessions that still have a NULL
event_id are back-filled to the same event on every re-run.

Run with:
    python seed_sessions.py

REQUIRES: seed_venues.py and seed_speakers.py should already have been
run, since these sessions reference those venues/speakers BY NAME. If
a named venue or speaker isn't found in the database, that one session
is skipped (with a printed warning) rather than crashing the script or
inserting a broken row.
"""

from app import app, has_session_conflict, parse_time_flexible
from models import db, Session, Venue, Speaker, Event
from datetime import datetime as dt


# ============================================================
# DEMO SESSION DATA
# Deliberately spread across 2 dates and several venues/speakers,
# with times chosen so nothing overlaps within this list itself.
# Includes a Cancelled and a Confirmed status alongside the default
# Scheduled, so the status badge has real variety to display.
# Expertise terms match the aliasing used by Speaker Recommendation
# (e.g. "AI/ML" matches Rahul Mehta's "AI/ML, Data Science").
# ============================================================
SESSIONS = [
    {
        "title": "Scaling with Cloud Native Architecture",
        "description": "Patterns for building resilient, horizontally scalable cloud systems.",
        "date": "2026-08-17", "start_time": "09:00", "end_time": "10:00",
        "venue_name": "Grand Orchid Convention Centre",
        "speaker_name": "Dr. Priya Sharma",
        "required_expertise": "Cloud Computing",
        "status": "Scheduled",
    },
    {
        "title": "Deep Learning in Production Systems",
        "description": "Taking ML models from notebooks to reliable production pipelines.",
        "date": "2026-08-17", "start_time": "09:00", "end_time": "10:00",
        "venue_name": "HITEC Convention Centre",
        "speaker_name": "Rahul Mehta",
        "required_expertise": "AI/ML",
        "status": "Scheduled",
    },
    {
        "title": "Modern Frontend Engineering",
        "description": "Component architecture and performance for large-scale web apps.",
        "date": "2026-08-17", "start_time": "10:15", "end_time": "11:15",
        "venue_name": "Silicon Suites Conference Hall",
        "speaker_name": "Ananya Iyer",
        "required_expertise": "Web Development",
        "status": "Scheduled",
    },
    {
        "title": "DevOps at Scale",
        "description": "CI/CD pipeline design for multi-team engineering organisations.",
        "date": "2026-08-17", "start_time": "10:15", "end_time": "11:15",
        "venue_name": "Grand Orchid Convention Centre",
        "speaker_name": "Arjun Kapoor",
        "required_expertise": "DevOps",
        "status": "Scheduled",
    },
    {
        "title": "Securing Cloud Workloads",
        "description": "Threat modelling and hardening for cloud-hosted infrastructure.",
        "date": "2026-08-17", "start_time": "11:30", "end_time": "12:30",
        "venue_name": "HITEC Convention Centre",
        "speaker_name": "Rohan Bhatt",
        "required_expertise": "Cyber Security, Cloud Computing",
        "status": "Confirmed",
    },
    {
        "title": "IoT for Smart Cities",
        "description": "Connected sensor networks and edge processing at municipal scale.",
        "date": "2026-08-18", "start_time": "09:00", "end_time": "10:00",
        "venue_name": "Capital Exhibition Hall",
        "speaker_name": "Kavya Reddy",
        "required_expertise": "Internet of Things (IoT)",
        "status": "Scheduled",
    },
    {
        "title": "AI-Powered Data Pipelines",
        "description": "Using machine learning to automate data quality and transformation.",
        "date": "2026-08-18", "start_time": "09:00", "end_time": "10:00",
        "venue_name": "Marina Grand Ballroom",
        "speaker_name": "Divya Menon",
        "required_expertise": "Data Science, AI/ML",
        "status": "Scheduled",
    },
    {
        "title": "Designing Accessible Interfaces",
        "description": "Practical accessibility patterns for real-world product teams.",
        "date": "2026-08-18", "start_time": "10:15", "end_time": "11:00",
        "venue_name": "Connaught Seminar Hall",
        "speaker_name": "Meera Pillai",
        "required_expertise": "UI/UX Design",
        "status": "Scheduled",
    },
    {
        "title": "Blockchain Fundamentals for Web Developers",
        "description": "An introduction to smart contracts and decentralised app design.",
        "date": "2026-08-18", "start_time": "11:15", "end_time": "12:15",
        "venue_name": "Hinjewadi Tech Auditorium",
        "speaker_name": "Nikhil Verma",
        "required_expertise": "Blockchain",
        "status": "Scheduled",
    },
    {
        "title": "Robotics and the Future of IoT",
        "description": "Where robotics and connected-device engineering are heading next.",
        "date": "2026-08-18", "start_time": "12:30", "end_time": "13:30",
        "venue_name": "Hinjewadi Tech Auditorium",
        "speaker_name": "Sandeep Chatterjee",
        "required_expertise": "Robotics, Internet of Things (IoT)",
        "status": "Cancelled",
    },
]

# The event all demo sessions belong to. Looked up by name at seed time
# so we never hardcode an id (which can differ between environments).
SESSION_EVENT_NAME = "TechConnect Summit 2026"


def seed():
    with app.app_context():
        # --- Resolve the target event ---
        event = Event.query.filter_by(name=SESSION_EVENT_NAME).first()
        if not event:
            print(
                f"Event '{SESSION_EVENT_NAME}' not found. "
                "Run seed_events.py (or seed_sponsors.py) first."
            )
            return

        inserted = 0
        skipped_missing = 0
        skipped_duplicate = 0
        skipped_conflict = 0

        for s in SESSIONS:
            venue = Venue.query.filter_by(name=s["venue_name"]).first()
            speaker = Speaker.query.filter_by(name=s["speaker_name"]).first()

            if not venue or not speaker:
                missing = []
                if not venue:
                    missing.append(f"venue '{s['venue_name']}'")
                if not speaker:
                    missing.append(f"speaker '{s['speaker_name']}'")
                print(f"Skipped '{s['title']}': {', '.join(missing)} not found. "
                      f"Run seed_venues.py / seed_speakers.py first.")
                skipped_missing += 1
                continue

            session_date = dt.strptime(s["date"], "%Y-%m-%d").date()

            # Duplicate-safe: identified by title + date together
            existing = Session.query.filter_by(title=s["title"], date=session_date).first()
            if existing:
                skipped_duplicate += 1
                # Back-fill event_id if the row predates Task 4
                if existing.event_id is None:
                    existing.event_id = event.id
                continue

            start_time = parse_time_flexible(s["start_time"])
            end_time = parse_time_flexible(s["end_time"])

            # Reuses the exact same conflict check used by /sessions/add,
            # so seeded data can never silently create a double-booking.
            conflict_message = has_session_conflict(
                session_date, start_time, end_time,
                venue_id=venue.id, speaker_id=speaker.id
            )
            if conflict_message:
                print(f"Skipped '{s['title']}': {conflict_message}")
                skipped_conflict += 1
                continue

            db.session.add(Session(
                title=s["title"],
                description=s["description"],
                date=session_date,
                start_time=start_time,
                end_time=end_time,
                venue_id=venue.id,
                speaker_id=speaker.id,
                required_expertise=s["required_expertise"],
                status=s["status"],
                event_id=event.id,
            ))
            inserted += 1

        # Back-fill any other existing sessions that still have no event_id
        backfilled = (
            Session.query
            .filter(Session.event_id.is_(None))
            .update({"event_id": event.id}, synchronize_session=False)
        )

        db.session.commit()
        print(f"\nInserted {inserted} new session(s). "
              f"Skipped {skipped_duplicate} duplicate(s), "
              f"{skipped_conflict} conflicting session(s), "
              f"{skipped_missing} with a missing venue/speaker.")
        if backfilled:
            print(f"Back-filled event_id on {backfilled} existing session(s).")


if __name__ == "__main__":
    seed()
