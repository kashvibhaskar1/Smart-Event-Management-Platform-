"""
seed_speakers.py

Inserts 15 realistic demo speakers into the existing SQLite database,
for testing Speaker Management (search, edit, availability).

Run with:
    python seed_speakers.py

NOTE: Same assumption as seed_data.py / seed_venues.py — this imports
your Flask app instance from app.py and the shared `db` object + Speaker
model from models.py. If your actual file/import names differ, update
the two import lines below.
"""

from app import app
from models import db, Speaker


# ============================================================
# DEMO SPEAKER DATA
# Deliberately varied: some speakers share an expertise area
# (so search-by-expertise returns multiple results), some are
# marked Unavailable, and some have no session_duration set —
# so every column/edge case in speakers.html has real data.
# ============================================================

SPEAKERS = [
    {
        "name": "Dr. Priya Sharma",
        "email": "priya.sharma@example.com",
        "organization": "Google India",
        "designation": "Principal Engineer",
        "expertise": "Cloud Computing, DevOps",
        "session_duration": 45,
        "availability": True,
    },
    {
        "name": "Rahul Mehta",
        "email": "rahul.mehta@example.com",
        "organization": "Microsoft India",
        "designation": "Senior Data Scientist",
        "expertise": "Artificial Intelligence & Machine Learning, Data Science",
        "session_duration": 60,
        "availability": True,
    },
    {
        "name": "Ananya Iyer",
        "email": "ananya.iyer@example.com",
        "organization": "Freshworks",
        "designation": "Lead Frontend Engineer",
        "expertise": "Web Development, UI/UX Design",
        "session_duration": 30,
        "availability": True,
    },
    {
        "name": "Vikram Nair",
        "email": "vikram.nair@example.com",
        "organization": "Independent Consultant",
        "designation": "Security Researcher",
        "expertise": "Cyber Security",
        "session_duration": 45,
        "availability": False,
    },
    {
        "name": "Kavya Reddy",
        "email": "kavya.reddy@example.com",
        "organization": "Amazon India",
        "designation": "Solutions Architect",
        "expertise": "Cloud Computing, Internet of Things (IoT)",
        "session_duration": 60,
        "availability": True,
    },
    {
        "name": "Arjun Kapoor",
        "email": "arjun.kapoor@example.com",
        "organization": "Zoho Corporation",
        "designation": "Engineering Manager",
        "expertise": "DevOps, Cloud Computing",
        "session_duration": None,
        "availability": True,
    },
    {
        "name": "Sneha Joshi",
        "email": "sneha.joshi@example.com",
        "organization": "IBM India",
        "designation": "AI Research Scientist",
        "expertise": "Artificial Intelligence & Machine Learning",
        "session_duration": 45,
        "availability": True,
    },
    {
        "name": "Karthik Subramaniam",
        "email": "karthik.s@example.com",
        "organization": "Tech Mahindra",
        "designation": "IoT Solutions Lead",
        "expertise": "Internet of Things (IoT), DevOps",
        "session_duration": 30,
        "availability": False,
    },
    {
        "name": "Divya Menon",
        "email": "divya.menon@example.com",
        "organization": "Flipkart",
        "designation": "Data Science Manager",
        "expertise": "Data Science, Artificial Intelligence & Machine Learning",
        "session_duration": 60,
        "availability": True,
    },
    {
        "name": "Rohan Bhatt",
        "email": "rohan.bhatt@example.com",
        "organization": "Cognizant",
        "designation": "Cybersecurity Consultant",
        "expertise": "Cyber Security, Cloud Computing",
        "session_duration": 45,
        "availability": True,
    },
    {
        "name": "Meera Pillai",
        "email": "meera.pillai@example.com",
        "organization": "Accenture",
        "designation": "UX Design Lead",
        "expertise": "UI/UX Design",
        "session_duration": 30,
        "availability": True,
    },
    {
        "name": "Nikhil Verma",
        "email": "nikhil.verma@example.com",
        "organization": "Wipro",
        "designation": "Blockchain Engineer",
        "expertise": "Blockchain, Web Development",
        "session_duration": None,
        "availability": True,
    },
    {
        "name": "Aishwarya Rao",
        "email": "aishwarya.rao@example.com",
        "organization": "Capgemini",
        "designation": "DevOps Architect",
        "expertise": "DevOps",
        "session_duration": 45,
        "availability": False,
    },
    {
        "name": "Sandeep Chatterjee",
        "email": "sandeep.c@example.com",
        "organization": "HCL Technologies",
        "designation": "Robotics Engineer",
        "expertise": "Robotics, Internet of Things (IoT)",
        "session_duration": 60,
        "availability": True,
    },
    {
        "name": "Ishita Das",
        "email": "ishita.das@example.com",
        "organization": "Infosys",
        "designation": "Full Stack Developer",
        "expertise": "Web Development, Cloud Computing",
        "session_duration": 30,
        "availability": True,
    },
]


def seed():
    with app.app_context():
        inserted = 0
        skipped = 0

        for s in SPEAKERS:
            # Duplicate-safe: same rule used by /speakers/add — identified by email
            existing = Speaker.query.filter_by(email=s["email"]).first()

            if existing:
                skipped += 1
                continue

            db.session.add(Speaker(
                name=s["name"],
                email=s["email"],
                organization=s["organization"],
                designation=s["designation"],
                expertise=s["expertise"],
                session_duration=s["session_duration"],
                availability=s["availability"],
            ))
            inserted += 1

        db.session.commit()
        print(f"Inserted {inserted} new speaker(s). Skipped {skipped} already-existing speaker(s).")


if __name__ == "__main__":
    seed()