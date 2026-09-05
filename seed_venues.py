"""
seed_venues.py

Inserts realistic demo venue data into the existing SQLite database,
for testing the Venue Recommendation Engine.

Run with:
    python seed_venues.py

NOTE: Same assumption as seed_data.py — this imports your Flask app
instance from app.py and the shared `db` object + Venue model from
models.py. If your actual file/import names differ, update the two
import lines below.
"""

from app import app
from models import db, Venue


# ============================================================
# DEMO VENUE DATA
# Spans all four capacity tiers, 7 locations, 6 venue types,
# a mix of facilities, and a mix of Available / Unavailable —
# so the recommendation engine has real variety to work with.
# ============================================================

VENUES = [
    # ---- Small (50-100) ----
    {
        "name": "Silicon Suites Conference Hall",
        "location": "Bangalore",
        "capacity": 80,
        "venue_type": "Conference Hall",
        "facilities": "WiFi, Projector, Air Conditioning",
        "cost": 8000,
        "availability": True,
    },
    {
        "name": "Banjara Conference Hall",
        "location": "Hyderabad",
        "capacity": 60,
        "venue_type": "Conference Hall",
        "facilities": "WiFi, Projector",
        "cost": 5000,
        "availability": False,
    },
    {
        "name": "OMR Seminar Hall",
        "location": "Chennai",
        "capacity": 100,
        "venue_type": "Seminar Hall",
        "facilities": "WiFi, Projector, Air Conditioning",
        "cost": 7000,
        "availability": True,
    },

    # ---- Medium (150-300) ----
    {
        "name": "Connaught Seminar Hall",
        "location": "Delhi",
        "capacity": 150,
        "venue_type": "Seminar Hall",
        "facilities": "WiFi, Projector, Video Conferencing",
        "cost": 15000,
        "availability": True,
    },
    {
        "name": "Hinjewadi Tech Auditorium",
        "location": "Pune",
        "capacity": 300,
        "venue_type": "Auditorium",
        "facilities": "WiFi, Projector, Audio System, Air Conditioning, Video Conferencing",
        "cost": 32000,
        "availability": True,
    },

    # ---- Large (400-700) ----
    {
        "name": "Regal Hotel Ballroom",
        "location": "Mumbai",
        "capacity": 400,
        "venue_type": "Hotel Ballroom",
        "facilities": "WiFi, Stage, Catering, Audio System, Air Conditioning, Parking",
        "cost": 65000,
        "availability": True,
    },
    {
        "name": "Marina Grand Ballroom",
        "location": "Chennai",
        "capacity": 500,
        "venue_type": "Hotel Ballroom",
        "facilities": "WiFi, Stage, Catering, Parking, Air Conditioning",
        "cost": 68000,
        "availability": True,
    },
    {
        "name": "HITEC Convention Centre",
        "location": "Hyderabad",
        "capacity": 700,
        "venue_type": "Convention Centre",
        "facilities": "WiFi, Parking, Stage, Audio System, Catering, Air Conditioning",
        "cost": 60000,
        "availability": True,
    },

    # ---- Very Large (800-1500) ----
    {
        "name": "Cyber Hub Exhibition Centre",
        "location": "Gurgaon",
        "capacity": 850,
        "venue_type": "Exhibition Hall",
        "facilities": "WiFi, Parking, Video Conferencing, Stage, Audio System, Catering",
        "cost": 95000,
        "availability": False,
    },
    {
        "name": "Marine Drive Auditorium",
        "location": "Mumbai",
        "capacity": 900,
        "venue_type": "Auditorium",
        "facilities": "Projector, Stage, Audio System, Air Conditioning, Video Conferencing",
        "cost": 72000,
        "availability": False,
    },
    {
        "name": "Grand Orchid Convention Centre",
        "location": "Bangalore",
        "capacity": 1200,
        "venue_type": "Convention Centre",
        "facilities": "WiFi, Projector, Parking, Stage, Audio System, Air Conditioning, Catering",
        "cost": 85000,
        "availability": True,
    },
    {
        "name": "Capital Exhibition Hall",
        "location": "Delhi",
        "capacity": 1500,
        "venue_type": "Exhibition Hall",
        "facilities": "WiFi, Parking, Stage, Video Conferencing, Catering, Air Conditioning",
        "cost": 110000,
        "availability": True,
    },
]


def seed():
    with app.app_context():
        inserted = 0
        skipped = 0

        for v in VENUES:
            # Duplicate-safe: same check used by the /venues/add route
            # (name + location together identify a venue)
            existing = Venue.query.filter_by(
                name=v["name"], location=v["location"]
            ).first()

            if existing:
                skipped += 1
                continue

            db.session.add(Venue(
                name=v["name"],
                location=v["location"],
                capacity=v["capacity"],
                venue_type=v["venue_type"],
                facilities=v["facilities"],
                cost=v["cost"],
                availability=v["availability"],
            ))
            inserted += 1

        db.session.commit()
        print(f"Inserted {inserted} new venue(s). Skipped {skipped} already-existing venue(s).")


if __name__ == "__main__":
    seed()