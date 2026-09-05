"""
seed_sponsors.py

Inserts demo sponsors, deliverables, leads, and event associations.
Also ensures the three demo events exist (calls seed_events internally).
Safe to re-run — all inserts are duplicate-checked.

Run with:
    python seed_sponsors.py
"""

from datetime import date
from app import app
from models import db, Sponsor, SponsorDeliverable, Event

# Which event each sponsor belongs to (looked up by name at seed time)
EVENT_ASSOCIATIONS = {
    "Nimbus Technologies":    "TechConnect Summit 2026",
    "Orbit Cloud Solutions":  "TechConnect Summit 2026",
    "Bright Path Analytics":  "TechConnect Summit 2026",
    "Startup Hub Collective": "DevDays Hyderabad 2026",
    "Legacy Systems Ltd.":    "DevDays Hyderabad 2026",
}

# Leads collected at the event/booth per sponsor (editable on the performance page)
LEADS = {
    "Nimbus Technologies":     45,
    "Orbit Cloud Solutions":   28,
    "Bright Path Analytics":   12,
    "Startup Hub Collective":   8,
    "Legacy Systems Ltd.":      0,
}

# Demo events (seeded first so FK references resolve)
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

SPONSORS = [
    {
        "company_name": "Nimbus Technologies",
        "contact_person": "Anjali Rao",
        "email": "anjali.rao@nimbustech.com",
        "phone": "9876543210",
        "package": "Platinum",
        "total_amount": 500000.0,
        "amount_paid": 500000.0,
        "contract_status": "Signed",
        "overall_status": "Confirmed",
    },
    {
        "company_name": "Orbit Cloud Solutions",
        "contact_person": "Vikram Shah",
        "email": "vikram.shah@orbitcloud.com",
        "phone": "9123456780",
        "package": "Gold",
        "total_amount": 250000.0,
        "amount_paid": 100000.0,
        "contract_status": "Signed",
        "overall_status": "Active",
    },
    {
        "company_name": "Bright Path Analytics",
        "contact_person": "Sneha Kapoor",
        "email": "sneha.kapoor@brightpath.io",
        "phone": "9988776655",
        "package": "Silver",
        "total_amount": 100000.0,
        "amount_paid": 5000.0,
        "contract_status": "Pending",
        "overall_status": "Active",
    },
    {
        "company_name": "Startup Hub Collective",
        "contact_person": "Meera Iyer",
        "email": "meera.iyer@startuphub.in",
        "phone": None,
        "package": "Custom",
        "total_amount": 50000.0,
        "amount_paid": 25000.0,
        "contract_status": "Signed",
        "overall_status": "Active",
    },
    {
        "company_name": "Legacy Systems Ltd.",
        "contact_person": "Rohan Desai",
        "email": "rohan.desai@legacysys.com",
        "phone": "9012345678",
        "package": "Gold",
        "total_amount": 250000.0,
        "amount_paid": 0.0,
        "contract_status": "Cancelled",
        "overall_status": "Cancelled",
    },
]

# Deliverables per sponsor
DELIVERABLES = {
    "Nimbus Technologies": [
        {
            "name": "Brand Logo on Main Stage Banner",
            "description": "Platinum logo placement on the main stage banner, visible to all attendees during keynote.",
            "due_date": date(2026, 8, 1),
            "status": "Completed",
        },
        {
            "name": "Full Page Ad in Event Brochure",
            "description": "Full-page colour advertisement in the official event brochure distributed to all attendees.",
            "due_date": date(2026, 7, 15),
            "status": "Completed",
        },
        {
            "name": "Exhibition Hall Booth Setup",
            "description": "Premium 6x6 m booth at a prime location in the exhibition hall.",
            "due_date": date(2026, 8, 10),
            "status": "Completed",
        },
        {
            "name": "Keynote Speaking Slot",
            "description": "10-minute speaking slot during the opening keynote session.",
            "due_date": date(2026, 8, 14),
            "status": "Completed",
        },
        {
            "name": "Post-Event Thank You Email Mention",
            "description": "Brand mention in the post-event thank-you email sent to all registered attendees.",
            "due_date": date(2026, 8, 20),
            "status": "In Progress",
        },
    ],
    "Orbit Cloud Solutions": [
        {
            "name": "Logo on Event Website",
            "description": "Gold tier logo placement on the sponsors section of the official event website.",
            "due_date": date(2026, 7, 10),
            "status": "Completed",
        },
        {
            "name": "Half Page Ad in Event Brochure",
            "description": "Half-page colour advertisement in the official event brochure.",
            "due_date": date(2026, 7, 20),
            "status": "Completed",
        },
        {
            "name": "Exhibition Booth",
            "description": "4x4 m exhibition booth at the venue.",
            "due_date": date(2026, 8, 10),
            "status": "In Progress",
        },
        {
            "name": "Social Media Shoutout (3 posts)",
            "description": "Three branded shoutout posts on official event social media channels (LinkedIn, Instagram, X).",
            "due_date": date(2026, 8, 14),
            "status": "Pending",
        },
    ],
    "Bright Path Analytics": [
        {
            "name": "Logo on Event Backdrop",
            "description": "Silver tier logo on the official photo/press backdrop at registration desk.",
            "due_date": date(2026, 8, 10),
            "status": "Pending",
        },
        {
            "name": "Quarter Page Ad in Event Brochure",
            "description": "Quarter-page advertisement in the official event brochure.",
            "due_date": date(2026, 7, 25),
            "status": "Pending",
        },
    ],
    "Startup Hub Collective": [
        {
            "name": "Startup Showcase Booth",
            "description": "Dedicated table at the startup showcase zone for product demonstrations.",
            "due_date": date(2026, 10, 10),
            "status": "Pending",
        },
        {
            "name": "Mention in Opening Address",
            "description": "Company name mentioned by the event host during the opening address.",
            "due_date": date(2026, 10, 10),
            "status": "Pending",
        },
    ],
    "Legacy Systems Ltd.": [
        {
            "name": "Contract Finalisation",
            "description": "Final review and signing of the sponsorship agreement. Sponsor later cancelled.",
            "due_date": date(2026, 6, 30),
            "status": "Pending",
        },
    ],
}


def seed():
    with app.app_context():
        # --- 1. Ensure demo events exist ---
        events_inserted = 0
        for e in EVENTS:
            if not Event.query.filter_by(name=e["name"]).first():
                db.session.add(Event(**e))
                events_inserted += 1
        db.session.commit()
        if events_inserted:
            print(f"Events    — inserted: {events_inserted}")

        # Build a name→id lookup for event FK assignment
        event_lookup = {e.name: e.id for e in Event.query.all()}

        # --- 2. Sponsors + deliverables ---
        sponsors_inserted = 0
        sponsors_skipped = 0
        deliverables_inserted = 0
        deliverables_skipped = 0

        for s in SPONSORS:
            event_name = EVENT_ASSOCIATIONS.get(s["company_name"])
            event_id = event_lookup.get(event_name)

            existing = Sponsor.query.filter_by(company_name=s["company_name"]).first()
            if existing:
                sponsors_skipped += 1
                sponsor_obj = existing
                # Refresh mutable fields on every re-run
                sponsor_obj.leads_count = LEADS.get(s["company_name"], 0)
                sponsor_obj.event_id = event_id
            else:
                sponsor_obj = Sponsor(
                    **s,
                    leads_count=LEADS.get(s["company_name"], 0),
                    event_id=event_id,
                )
                db.session.add(sponsor_obj)
                db.session.flush()
                sponsors_inserted += 1

            for d in DELIVERABLES.get(s["company_name"], []):
                existing_del = SponsorDeliverable.query.filter_by(
                    sponsor_id=sponsor_obj.id, name=d["name"]
                ).first()
                if existing_del:
                    deliverables_skipped += 1
                else:
                    db.session.add(SponsorDeliverable(
                        sponsor_id=sponsor_obj.id,
                        name=d["name"],
                        description=d.get("description"),
                        due_date=d.get("due_date"),
                        status=d.get("status", "Pending"),
                    ))
                    deliverables_inserted += 1

        db.session.commit()
        print(f"Sponsors  — inserted: {sponsors_inserted}, skipped (refreshed): {sponsors_skipped}")
        print(f"Deliverables — inserted: {deliverables_inserted}, skipped: {deliverables_skipped}")


if __name__ == "__main__":
    seed()
