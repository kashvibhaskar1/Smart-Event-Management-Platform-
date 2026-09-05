from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Attendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    fullname = db.Column(db.String(100), nullable=False)

    email = db.Column(db.String(100), unique=True, nullable=False)

    phone = db.Column(db.String(15), unique=True, nullable=False)

    age = db.Column(db.Integer, nullable=False)

    gender = db.Column(db.String(20), nullable=False)

    organization = db.Column(db.String(150), nullable=False)

    interest = db.Column(db.String(100), nullable=False)
    
    designation = db.Column(db.String(100))

    city = db.Column(db.String(100), nullable=False)

    state = db.Column(db.String(100), nullable=False)

    registration_time = db.Column(db.DateTime, default=datetime.utcnow)

    status = db.Column(db.String(30), default="Registered")

    # Server-side timestamps for attendee-side and admin-side check-in/out.
    # Nullable since they're only set once the corresponding action happens.
    check_in_time = db.Column(db.DateTime, nullable=True)

    check_out_time = db.Column(db.DateTime, nullable=True)

    # Which session (from the Session table below) this attendee chose
    # during registration. Nullable so existing rows created before this
    # change aren't broken by a required column with no value.
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)

    # Convenience relationship (no schema change — relationships aren't
    # columns) so we can read attendee.session.title / .venue / .speaker
    # directly instead of writing a manual query every time.
    session = db.relationship('Session', backref=db.backref('attendees', lazy=True))


# ============================================================
# MILESTONE 2 — Venue Agent
# ============================================================
class Venue(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(150), nullable=False)

    location = db.Column(db.String(150), nullable=False)

    capacity = db.Column(db.Integer, nullable=False)

    venue_type = db.Column(db.String(100))

    facilities = db.Column(db.Text)

    cost = db.Column(db.Float, nullable=False, default=0.0)

    availability = db.Column(db.Boolean, default=True)

    unavailable_reason = db.Column(db.String(255), nullable=True)


class VenueBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    venue_id = db.Column(db.Integer, db.ForeignKey('venue.id'), nullable=False)

    event_name = db.Column(db.String(150), nullable=False)

    booking_date = db.Column(db.Date, nullable=False)

    start_time = db.Column(db.Time, nullable=True)

    end_time = db.Column(db.Time, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    venue = db.relationship('Venue', backref=db.backref('bookings', lazy=True))


# ============================================================
# MILESTONE 2 — Speaker Agent (Step 1: Speaker Management)
# ============================================================
class Speaker(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(150), nullable=False)

    email = db.Column(db.String(150), unique=True, nullable=False)

    organization = db.Column(db.String(150))

    designation = db.Column(db.String(150))

    expertise = db.Column(db.String(255), nullable=False)

    availability = db.Column(db.Boolean, default=True)

    session_duration = db.Column(db.Integer, nullable=True)  # in minutes


# ============================================================
# MILESTONE 2 — Session Management (Step 2)
# ============================================================
class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)

    description = db.Column(db.Text, nullable=True)

    date = db.Column(db.Date, nullable=False)

    start_time = db.Column(db.Time, nullable=False)

    end_time = db.Column(db.Time, nullable=False)

    venue_id = db.Column(db.Integer, db.ForeignKey('venue.id'), nullable=True)

    required_expertise = db.Column(db.String(255), nullable=True)

    speaker_id = db.Column(db.Integer, db.ForeignKey('speaker.id'), nullable=True)

    status = db.Column(db.String(30), default="Scheduled")

    # Which overall event this session belongs to.
    # Nullable so all pre-existing session rows are preserved.
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)

    venue = db.relationship('Venue', backref=db.backref('sessions', lazy=True))
    speaker = db.relationship('Speaker', backref=db.backref('sessions', lazy=True))
    event = db.relationship('Event', backref=db.backref('sessions', lazy=True))


# ============================================================
# MILESTONE 3 — Event model (sponsor/future-feature association)
# Nullable FK on Sponsor so all pre-existing sponsor rows are
# preserved; existing records simply show "—" for event.
# ============================================================
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    date_display = db.Column(db.String(100))   # e.g. "Aug 14–15, 2026"
    location = db.Column(db.String(200))


# ============================================================
# MILESTONE 3 — Sponsor Management (Task 1: foundation)
# ============================================================
class Sponsor(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_name = db.Column(db.String(150), nullable=False)

    contact_person = db.Column(db.String(150), nullable=False)

    email = db.Column(db.String(150), nullable=False)

    phone = db.Column(db.String(20))

    package = db.Column(db.String(30), nullable=False)  # Platinum / Gold / Silver / Custom

    total_amount = db.Column(db.Float, nullable=False, default=0.0)

    amount_paid = db.Column(db.Float, nullable=False, default=0.0)

    contract_status = db.Column(db.String(30), default="Pending")

    overall_status = db.Column(db.String(30), default="Active")

    # Nullable so existing sponsor rows without an event are not broken
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    event = db.relationship('Event', backref=db.backref('sponsors', lazy=True))

    leads_count = db.Column(db.Integer, nullable=False, default=0)

    # Future: session-level sponsorship.
    # Allows a sponsor to be tied to one specific session within an event,
    # in addition to (or instead of) the overall event association above.
    # No UI yet — data structure only.
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    sponsored_session = db.relationship('Session', backref=db.backref('sponsors', lazy=True))

    deliverables = db.relationship(
        'SponsorDeliverable', backref='sponsor', lazy=True, cascade='all, delete-orphan'
    )

    @property
    def pending_amount(self):
        # Not stored — always derived from total_amount / amount_paid,
        # so it can never drift out of sync with the two real columns.
        return max(self.total_amount - self.amount_paid, 0)

    # ========================================================
    # MILESTONE 3 — Sponsorship data foundation
    # Real attendee/check-in counts for this sponsor's associated
    # Event/Session, reusing the EXISTING Attendee.session_id and
    # Session.event_id relationships already used by Registration
    # and Check-in/Check-out. No new columns, no stored numbers —
    # these are live queries every time they're read, so they can
    # never go stale or be faked. Scope: the specific sponsored
    # session if one is set, otherwise every session under the
    # sponsor's event. Returns None if the sponsor has no event.
    # ========================================================
    @property
    def registered_attendee_count(self):
        if self.session_id:
            return len(self.sponsored_session.attendees) if self.sponsored_session else 0
        if self.event_id:
            return sum(len(s.attendees) for s in self.event.sessions) if self.event else 0
        return None

    @property
    def checked_in_attendee_count(self):
        if self.session_id:
            return (sum(1 for a in self.sponsored_session.attendees if a.check_in_time)
                    if self.sponsored_session else 0)
        if self.event_id:
            return (sum(1 for s in self.event.sessions for a in s.attendees if a.check_in_time)
                    if self.event else 0)
        return None


class SponsorDeliverable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sponsor_id = db.Column(db.Integer, db.ForeignKey('sponsor.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), default="Pending")  # Pending, In Progress, Completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================================================
# MILESTONE 3 — Sponsor Interaction / Engagement tracking
# A real, logged interaction between a sponsor and an attendee at a
# specific event (and optionally a specific session). Performance
# calculations (Leads, Engagement %, Booth Visits, Attendee
# Interactions) are derived from real rows here — never from a
# manually-typed count and never against the whole system's
# attendees. No rows exist until an admin actually logs one.
# ============================================================
class SponsorInteraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    sponsor_id = db.Column(db.Integer, db.ForeignKey('sponsor.id'), nullable=False)

    # Which attendee this interaction is with. Required now — every
    # interaction is self-recorded by a specific attendee on their own
    # attendee-side page, never a free-choice "no attendee" entry.
    attendee_id = db.Column(db.Integer, db.ForeignKey('attendee.id'), nullable=False)

    # Scope: the Session this happened at — always the attendee's own
    # registered session. There is deliberately NO separate event_id
    # column here: the Event is already reachable via session.event,
    # so storing it a second time would just be a second source of
    # truth that could drift out of sync with the real relationship.
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)

    interaction_type = db.Column(db.String(30), nullable=False)  # Booth Visit / Lead Generated / Attendee Interaction

    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sponsor = db.relationship('Sponsor', backref=db.backref('interactions', lazy=True))
    attendee = db.relationship('Attendee', backref=db.backref('sponsor_interactions', lazy=True))
    session = db.relationship('Session', backref=db.backref('sponsor_interactions', lazy=True))


# ============================================================
# MILESTONE 3 — Incident Agent (basic Incident Management)
# ============================================================
class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)

    description = db.Column(db.Text, nullable=True)

    category = db.Column(db.String(100), nullable=True)

    location = db.Column(db.String(200), nullable=True)

    reported_time = db.Column(db.DateTime, default=datetime.utcnow)

    severity = db.Column(db.String(20), nullable=False, default="Low")  # Low / Medium / High / Critical

    # Workflow: Logged -> Investigating -> Resolved -> Closed (forward only).
    # Status is no longer freely editable via a generic edit form — it only
    # ever changes through the dedicated workflow transition routes, which
    # enforce the correct sequence and the Resolution Notes requirement.
    status = db.Column(db.String(20), nullable=False, default="Logged")

    # Free-text — no Staff/Team model exists in this project, and inventing
    # one wasn't part of this task, so this stays a simple optional field.
    assigned_to = db.Column(db.String(150), nullable=True)

    # ------------------------------------------------------------
    # Workflow timestamps and resolution notes. All nullable since
    # they're only set once the corresponding transition happens —
    # existing incidents (created before this change) simply have
    # these as empty until they're moved through the workflow.
    # ------------------------------------------------------------
    investigation_started_at = db.Column(db.DateTime, nullable=True)

    resolved_at = db.Column(db.DateTime, nullable=True)

    resolution_notes = db.Column(db.Text, nullable=True)

    closed_at = db.Column(db.DateTime, nullable=True)

    # ------------------------------------------------------------
    # Priority and escalation are NOT stored columns — both are pure
    # functions of the real severity/status values, computed fresh on
    # every read, so they can never drift out of sync with them (no
    # migration needed either, since nothing new is added to the table).
    # ------------------------------------------------------------
    @property
    def priority(self):
        return {
            "Low": "Low",
            "Medium": "Medium",
            "High": "High",
            "Critical": "Urgent",
        }.get(self.severity, "Low")

    @property
    def is_escalated(self):
        # A Resolved or Closed incident is never considered escalated,
        # regardless of how severe it originally was.
        if self.status in ("Resolved", "Closed"):
            return False
        return self.severity in ("High", "Critical")

    # ------------------------------------------------------------
    # Explicit escalation record. Distinct from the `is_escalated`
    # property above: is_escalated is an automatic, computed signal
    # ("this incident's severity currently warrants attention") that
    # can never be stale since it's derived fresh every read. `escalated`
    # here is a real, stored fact — whether an admin has actually
    # performed the escalation action, and to whom/why/when. Both are
    # useful for different things: is_escalated drives the always-on
    # visual warning badge; `escalated` drives the actual audit trail.
    # ------------------------------------------------------------
    escalated = db.Column(db.Boolean, default=False)

    escalated_to = db.Column(db.String(150), nullable=True)

    escalated_at = db.Column(db.DateTime, nullable=True)

    escalation_reason = db.Column(db.Text, nullable=True)

    # ------------------------------------------------------------
    # Contact details. Free-text, same reasoning as assigned_to above —
    # no Contact/Staff model exists in this project, so nothing here
    # is a dropdown of preset names; every value is whatever the admin
    # actually types in for this specific incident.
    # ------------------------------------------------------------
    contact_person = db.Column(db.String(150), nullable=True)

    contact_phone = db.Column(db.String(30), nullable=True)

    alternate_contact = db.Column(db.String(150), nullable=True)

    # Who actually resolved it — distinct from resolution_notes/resolved_at
    # above (which already existed and are reused as-is for "what/when").
    resolved_by = db.Column(db.String(150), nullable=True)


# ============================================================
# MILESTONE 4 — Intelligence Engine: cross-module alerts
#
# Deliberately a SEPARATE concept from Incident. An Incident is
# something a person manually reports (an admin fills in a form).
# An IntelligenceAlert is something the system detects automatically
# by analyzing real data across modules (capacity, registration
# velocity, conflicts, sponsor risk, repeated incidents, etc). They
# can reference each other (e.g. an alert about a high-severity
# incident links incident_id) without duplicating any data — every
# FK here is nullable and only set when actually relevant.
# ============================================================
class IntelligenceAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # e.g. "Venue Capacity", "Registration Surge", "Check-in Queue",
    # "Session Conflict", "High-Severity Incident", "Repeated Incidents",
    # "Sponsor Risk"
    alert_type = db.Column(db.String(50), nullable=False)

    severity = db.Column(db.String(20), nullable=False, default="Informational")  # Informational / Warning / Critical

    message = db.Column(db.Text, nullable=False)

    source_module = db.Column(db.String(50), nullable=False)  # Registration / Check-in / Venue / Session / Sponsor / Incident

    recommendation = db.Column(db.Text, nullable=True)

    # Real references — whichever is relevant to this specific alert.
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    venue_id = db.Column(db.Integer, db.ForeignKey('venue.id'), nullable=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incident.id'), nullable=True)
    sponsor_id = db.Column(db.Integer, db.ForeignKey('sponsor.id'), nullable=True)

    detected_at = db.Column(db.DateTime, default=datetime.utcnow)

    status = db.Column(db.String(20), nullable=False, default="Active")  # Active / Acknowledged / Resolved
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    event = db.relationship('Event')
    session = db.relationship('Session')
    venue = db.relationship('Venue')
    incident = db.relationship('Incident')
    sponsor = db.relationship('Sponsor')


# ============================================================
# MILESTONE 4, PART 3 — Agent Orchestration audit trail.
#
# One row per orchestration run. Persisted (not just an in-memory
# dict) so a run's outcome survives a server restart and can be
# reviewed later — matching how every other workflow in this project
# keeps a real record rather than a transient result.
# ============================================================
class OrchestrationRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    workflow_name = db.Column(db.String(100), nullable=False, default="Session Cancellation")

    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incident.id'), nullable=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('intelligence_alert.id'), nullable=True)

    # Real facts gathered/produced by each agent step, in order —
    # kept as a JSON-serialized list of {agent, status, summary} dicts
    # so the full sequence can be displayed without needing five
    # separate tables for something that's read as one narrative.
    steps_json = db.Column(db.Text, nullable=False, default="[]")

    affected_attendee_count = db.Column(db.Integer, nullable=False, default=0)
    alternative_venue_count = db.Column(db.Integer, nullable=False, default=0)

    escalated = db.Column(db.Boolean, default=False)
    escalation_reason = db.Column(db.Text, nullable=True)

    # Human-approval gate for the one consequential, hard-to-reverse
    # action in this workflow: emailing real attendees. Never sent
    # automatically by the orchestrator itself.
    notification_status = db.Column(db.String(20), nullable=False, default="Pending Approval")  # Pending Approval / Approved / Sent / Declined
    approved_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="Completed")  # Completed / Failed / Partial
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    session = db.relationship('Session')
    incident = db.relationship('Incident')
    alert = db.relationship('IntelligenceAlert')