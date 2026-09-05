"""
seed_data.py

Inserts 30 realistic demo attendees into the existing SQLite database.

Run with:
    python seed_data.py

NOTE: This script assumes the same project layout used throughout this
project — a Flask app instance in app.py and the Attendee model (plus the
shared `db` SQLAlchemy object) in models.py. If your actual file/import
names differ, update the two import lines below to match.
"""

import random
from datetime import datetime, timedelta

from app import app          # your Flask app instance
from models import db, Attendee   # your SQLAlchemy db object + Attendee model


# ============================================================
# SAMPLE DATA POOLS
# ============================================================

FIRST_NAMES_MALE = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Karthik", "Rahul", "Amit", "Suresh", "Vikram", "Nikhil",
    "Manish", "Sandeep", "Deepak", "Abhishek",
]

FIRST_NAMES_FEMALE = [
    "Ananya", "Diya", "Saanvi", "Aadhya", "Kavya", "Ishita", "Priya", "Sneha",
    "Meera", "Pooja", "Riya", "Neha", "Kritika", "Divya", "Shreya", "Anjali",
    "Nisha", "Swati", "Aishwarya", "Lakshmi",
]

LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Reddy", "Iyer", "Nair", "Menon", "Rao",
    "Patel", "Shah", "Kumar", "Singh", "Das", "Chatterjee", "Bhat", "Pillai",
    "Joshi", "Mehta", "Kapoor", "Agarwal",
]

CITIES_STATES = [
    ("Bangalore", "Karnataka"),
    ("Delhi", "Delhi"),
    ("Mumbai", "Maharashtra"),
    ("Pune", "Maharashtra"),
    ("Hyderabad", "Telangana"),
    ("Chennai", "Tamil Nadu"),
    ("Jaipur", "Rajasthan"),
    ("Gurgaon", "Haryana"),
    ("Kolkata", "West Bengal"),
    ("Ahmedabad", "Gujarat"),
    ("Noida", "Uttar Pradesh"),
    ("Kochi", "Kerala"),
]

ORGANIZATIONS = [
    "Infosys", "TCS", "Wipro", "HCL Technologies", "Tech Mahindra", "Accenture",
    "Capgemini", "Cognizant", "IBM India", "Google India", "Amazon India",
    "Microsoft India", "Freshworks", "Zoho Corporation", "Flipkart",
]

DESIGNATIONS = [
    "Software Engineer", "Senior Software Engineer", "Systems Analyst",
    "Product Manager", "Data Analyst", "DevOps Engineer", "QA Engineer",
    "Technical Lead", "Associate Consultant", "Business Analyst", "Intern",
    "UI/UX Designer",
]

INTERESTS = [
    "Artificial Intelligence & Machine Learning",
    "Web Development",
    "Cyber Security",
    "Cloud Computing",
    "Data Science",
    "Internet of Things (IoT)",
    "DevOps",
]

GENDERS = ["Male", "Female"]

STATUSES = ["Registered", "Checked In", "Checked Out"]

EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com"]


# ============================================================
# HELPERS
# ============================================================

def random_phone(used_phones):
    """Generate a 10-digit Indian-style mobile number not already used."""
    while True:
        phone = "9" + "".join(str(random.randint(0, 9)) for _ in range(9))
        if phone not in used_phones:
            return phone


def random_email(fullname, used_emails):
    """Generate an email from the attendee's name, guaranteed unique."""
    base = fullname.lower().replace(" ", ".")
    while True:
        domain = random.choice(EMAIL_DOMAINS)
        email = f"{base}{random.randint(1, 9999)}@{domain}"
        if email not in used_emails:
            return email


def random_registration_time():
    """Random timestamp within the last 20 days."""
    start = datetime.now() - timedelta(days=20)
    offset_seconds = random.randint(0, 20 * 24 * 60 * 60)
    return start + timedelta(seconds=offset_seconds)


# ============================================================
# SEED LOGIC
# ============================================================

def seed(count=30):
    with app.app_context():
        existing_emails = {a.email for a in Attendee.query.all()}
        existing_phones = {a.phone for a in Attendee.query.all()}

        created = 0

        for _ in range(count):
            gender = random.choice(GENDERS)
            first_name = random.choice(
                FIRST_NAMES_MALE if gender == "Male" else FIRST_NAMES_FEMALE
            )
            last_name = random.choice(LAST_NAMES)
            fullname = f"{first_name} {last_name}"

            email = random_email(fullname, existing_emails)
            phone = random_phone(existing_phones)
            city, state = random.choice(CITIES_STATES)

            attendee = Attendee(
                fullname=fullname,
                email=email,
                phone=phone,
                age=random.randint(18, 45),
                gender=gender,
                organization=random.choice(ORGANIZATIONS),
                designation=random.choice(DESIGNATIONS),
                city=city,
                state=state,
                interest=random.choice(INTERESTS),
                status=random.choice(STATUSES),
                registration_time=random_registration_time(),
            )

            db.session.add(attendee)
            existing_emails.add(email)
            existing_phones.add(phone)
            created += 1

        db.session.commit()
        print(f"Inserted {created} demo attendees into the database.")


if __name__ == "__main__":
    seed(30)