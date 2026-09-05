from functools import wraps
from flask import Flask, render_template, request, redirect, flash, url_for, session, jsonify, Response
from models import db, Attendee, Venue, VenueBooking, Speaker, Session, Sponsor, SponsorDeliverable, Event, SponsorInteraction, Incident, IntelligenceAlert, OrchestrationRun
import intelligence_engine
import agent_orchestrator
from collections import Counter
from datetime import datetime
import csv
import io
import json
import smtplib
from email.mime.text import MIMEText

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "kashvibhaskar1@gmail.com"        # the Gmail account sending the email
SENDER_PASSWORD = "quyoyowumekuiepf"             # the 16-character App Password (no spaces)

# Hardcoded admin credentials (simple auth for this milestone)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# ============================================================
# EVENT CONFIGURATION — single source of truth for the one event
# this system manages. Previously this same information was
# duplicated independently inside home.html and dashboard.html
# (each with its own hardcoded copy). Every template that needs
# event details now reads from this dict via the view functions
# below, instead of hardcoding its own values.
#
# This project has no Event database table and manages exactly
# one event, so a plain config dict is used rather than adding a
# new model/table for a single row of data.
# ============================================================
EVENT_INFO = {
    "name": "TechConnect Summit 2026",
    "date_display": "Aug 14\u201315, 2026",
    "location": "Bangalore International Centre",
    "organizer": "Nimbus Events Pvt. Ltd.",
    "capacity": 500,
}

app = Flask(__name__)
app.secret_key = "any-random-text-you-want"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# ============================================================
# ACCESS CONTROL
# ============================================================
def login_required(f):
    """Blocks access to a route unless session['admin_logged_in'] is True."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ============================================================
# EMAIL HELPER
# ============================================================
def send_confirmation_email(attendee):
    # Pull the real session details the attendee actually selected —
    # never hardcode an event/session name here. Falls back gracefully
    # if for some reason no session is attached to this attendee.
    session_obj = attendee.session

    event_name = session_obj.title if session_obj else "Your Registered Event"
    session_date = session_obj.date.strftime("%B %d, %Y") if session_obj else "To be announced"
    session_venue = session_obj.venue.name if (session_obj and session_obj.venue) else "To be announced"

    speaker_line = ""
    if session_obj and session_obj.speaker:
        speaker_line = f"Speaker: {session_obj.speaker.name}\n"

    status_url = url_for("attendee_status", attendee_id=attendee.id, _external=True)

    subject = f"Registration Confirmed \u2013 {event_name}"

    body = f"""Hello {attendee.fullname},

Thank you for registering for {event_name}.
Your registration has been successfully recorded.

Registration Details:
Name: {attendee.fullname}
Email: {attendee.email}
Organization: {attendee.organization}
Area of Interest: {attendee.interest}
Registration ID: {attendee.id}
Current Status: {attendee.status}

Session Details:
Session: {event_name}
Date: {session_date}
Venue: {session_venue}
{speaker_line}
View your registration status and check in/out here:
{status_url}

We look forward to seeing you at the event.

Regards,
Event Management Team
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = attendee.email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, attendee.email, msg.as_string())


def send_cancellation_email(attendee, session_obj):
    """
    Sent only when an admin explicitly approves it from the
    orchestration result page — never sent automatically by the
    orchestrator itself. Reuses the exact same SMTP configuration and
    smtplib/MIMEText pattern as send_confirmation_email() above.
    """
    session_title = session_obj.title if session_obj else "your session"
    subject = f"Session Cancelled: {session_title}"

    body = f"""Hello {attendee.fullname},

We're sorry to inform you that the following session has been cancelled:

Session: {session_title}
{"Date: " + session_obj.date.strftime("%B %d, %Y") if session_obj and session_obj.date else ""}

Our team is working on alternative arrangements. Please check your registration status page for updates.

Regards,
Event Management Team
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = attendee.email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, attendee.email, msg.as_string())


def send_speaker_schedule_email(speaker, session_obj, mode="confirmation"):
    """
    Sends a session schedule email to a speaker, reusing the exact same
    SMTP configuration and smtplib/MIMEText pattern as send_confirmation_email()
    above (same Gmail account, same helper libraries — nothing new added).

    mode:
      "confirmation" — speaker newly assigned to this session
      "update"       — same speaker, but session details changed (date/time/venue/etc.)
      "cancellation" — speaker was removed/replaced on this session
    """
    venue_name = session_obj.venue.name if session_obj.venue else "Not yet assigned"

    if mode == "cancellation":
        subject = f"Session Reassignment Notice: {session_obj.title}"
        body = f"""Hello {speaker.name},

You have been removed from the following session, which has since been reassigned:

Session: {session_obj.title}
Date: {session_obj.date}
Time: {session_obj.start_time.strftime('%H:%M')} - {session_obj.end_time.strftime('%H:%M')}
Venue: {venue_name}

If you believe this is a mistake, please contact the event organizing team.

Regards,
Event Management Team
"""
    else:
        if mode == "update":
            subject = f"Session Schedule Updated: {session_obj.title}"
            intro = "Your session schedule has been updated. Please review the details below:"
        else:
            subject = f"Speaker Session Confirmed: {session_obj.title}"
            intro = "You have been confirmed as a speaker for the following session:"

        body = f"""Hello {speaker.name},

{intro}

Session Title: {session_obj.title}
Topic: {session_obj.description or 'N/A'}
Date: {session_obj.date}
Start Time: {session_obj.start_time.strftime('%H:%M')}
End Time: {session_obj.end_time.strftime('%H:%M')}
Venue: {venue_name}

Thank you for being part of this event.

Regards,
Event Management Team
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = speaker.email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, speaker.email, msg.as_string())


# ============================================================
# PUBLIC / ATTENDEE-FACING ROUTES (no login required)
# ============================================================
@app.route("/")
def home():
    return render_template("home.html", event_info=EVENT_INFO)


@app.route("/register", methods=["GET", "POST"])
def register():

    registered_count = Attendee.query.count()
    remaining_slots = max(EVENT_INFO["capacity"] - registered_count, 0)

    # Sessions the attendee can choose from — existing Session records only.
    # This is read-only from the attendee side; nothing here creates or
    # edits a Session.
    available_sessions = Session.query.order_by(Session.date, Session.start_time).all()

    if request.method == "POST":

        fullname = request.form["fullname"]
        email = request.form["email"]
        phone = request.form["phone"]
        age = request.form["age"]
        gender = request.form["gender"]
        organization = request.form["organization"]
        interest = request.form["interest"]
        designation = request.form["designation"]
        city = request.form["city"]
        state = request.form["state"]
        session_id_str = request.form.get("session_id", "").strip()

        # Check duplicate email
        existing_email = Attendee.query.filter_by(email=email).first()
        if existing_email:
            flash("This email is already registered.", "error")
            return redirect(url_for("register"))

        # Check duplicate phone
        existing_phone = Attendee.query.filter_by(phone=phone).first()
        if existing_phone:
            flash("This phone number is already registered.", "error")
            return redirect(url_for("register"))

        # Check event registration capacity — this is the EVENT's overall
        # capacity (EVENT_INFO["capacity"]), not any individual session/venue
        # capacity, which is a separate concept managed under Sessions/Venues.
        if registered_count >= EVENT_INFO["capacity"]:
            flash("No slots are currently available for this event.", "error")
            return redirect(url_for("register"))

        # A session must be selected
        if not session_id_str:
            flash("Please select a session to register for.", "error")
            return redirect(url_for("register"))

        selected_session = Session.query.get(session_id_str)
        if not selected_session:
            flash("The selected session no longer exists. Please choose another.", "error")
            return redirect(url_for("register"))

        # ---- PER-SESSION capacity check, based on that session's venue ----
        # Independent of the event-wide capacity check above: a full session
        # does not make the whole event full, and other sessions with room
        # remain selectable. Existing venue booking logic (VenueBooking) is
        # untouched — this only counts Attendee rows against this Session.
        if selected_session.venue:
            venue_capacity = selected_session.venue.capacity
            current_session_registrations = Attendee.query.filter_by(session_id=selected_session.id).count()

            if current_session_registrations >= venue_capacity:
                flash(
                    "Session Full \u2014 This session has reached venue capacity. "
                    "Please select another session.",
                    "error"
                )
                return redirect(url_for("register"))

        # Create attendee
        new_attendee = Attendee(
            fullname=fullname,
            email=email,
            phone=phone,
            age=age,
            gender=gender,
            organization=organization,
            interest=interest,
            designation=designation,
            city=city,
            state=state,
            session_id=selected_session.id
        )

        db.session.add(new_attendee)
        db.session.commit()

        try:
            send_confirmation_email(new_attendee)
        except Exception as e:
            print(f"Email sending failed: {e}")

        return render_template("success.html", attendee=new_attendee, event_info=EVENT_INFO)

    # GET request
    return render_template(
        "register.html",
        event_info=EVENT_INFO,
        registered_count=registered_count,
        remaining_slots=remaining_slots,
        available_sessions=available_sessions,
    )


# ============================================================
# ADMIN AUTH ROUTES (no login required to reach /login itself)
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login"))


# ============================================================
# ADMIN-ONLY ROUTES (login required)
# ============================================================
@app.route("/dashboard")
@login_required
def dashboard():

    all_attendees = Attendee.query.order_by(Attendee.registration_time.desc()).all()

    total = len(all_attendees)

    # Counts are derived from the real check_in_time / check_out_time
    # timestamps — the actual data created by the Check In / Check Out
    # actions — rather than trusting the status string in isolation.
    #   Registered   = never checked in (no check_in_time)
    #   Checked In   = checked in, not yet checked out
    #   Currently Inside = same population as Checked In (still on-site)
    #   Checked Out  = has a check_out_time, regardless of anything else
    registered = sum(1 for a in all_attendees if not a.check_in_time)
    checked_in = sum(1 for a in all_attendees if a.check_in_time and not a.check_out_time)
    checked_out = sum(1 for a in all_attendees if a.check_out_time)
    inside = checked_in

    attendees = all_attendees[:5]

    city_counts = Counter(a.city for a in all_attendees if a.city)
    gender_counts = Counter(a.gender for a in all_attendees if a.gender)

    top_city = city_counts.most_common(1)[0][0] if city_counts else "N/A"
    top_gender = gender_counts.most_common(1)[0][0] if gender_counts else "N/A"

    ages = []
    for a in all_attendees:
        try:
            if a.age:
                ages.append(int(a.age))
        except (ValueError, TypeError):
            pass
    avg_age = round(sum(ages) / len(ages), 1) if ages else 0

    date_counts = Counter(
        a.registration_time.strftime("%b %d") for a in all_attendees if a.registration_time
    )
    trend_labels = sorted(date_counts.keys(), key=lambda d: datetime.strptime(d, "%b %d"))
    trend_values = [date_counts[d] for d in trend_labels]

    gender_labels = list(gender_counts.keys())
    gender_values = list(gender_counts.values())

    state_counts = Counter(a.state for a in all_attendees if a.state)
    state_labels = list(state_counts.keys())
    state_values = list(state_counts.values())

    # ============================================================
    # MILESTONE 4, PART 2 — Executive Dashboard additions.
    # Everything below is ADDITIONAL data for the new executive layer.
    # Nothing above this line was touched — all existing dashboard
    # data/behavior is preserved exactly as it was.
    # ============================================================

    # --- Attendance rate: real % of registered attendees who actually
    # showed up (checked in at some point, whether still inside or
    # already checked out) ---
    attendance_rate = round(((checked_in + checked_out) / total) * 100, 1) if total else 0

    # --- Check-in trend: same real-timestamp pattern already used for
    # the registration trend above, just keyed on check_in_time instead ---
    checkin_date_counts = Counter(
        a.check_in_time.strftime("%b %d") for a in all_attendees if a.check_in_time
    )
    if checkin_date_counts:
        checkin_trend_labels = sorted(checkin_date_counts.keys(), key=lambda d: datetime.strptime(d, "%b %d"))
        checkin_trend_values = [checkin_date_counts[d] for d in checkin_trend_labels]
    else:
        checkin_trend_labels, checkin_trend_values = [], []

    # --- Sponsor KPIs: reuses the real, already-tested performance
    # calculation exactly as-is — not recomputed or duplicated here ---
    sponsor_perf_data, _ = compute_sponsor_performance()
    total_sponsors = len(sponsor_perf_data)
    avg_sponsor_score = round(sum(i["overall_score"] for i in sponsor_perf_data) / total_sponsors, 1) if total_sponsors else None
    sponsor_status_counts = Counter(i["perf_status"] for i in sponsor_perf_data)

    # --- Incident KPIs: real counts from the Incident table ---
    all_incidents_list = Incident.query.all()
    open_incidents_count = sum(1 for i in all_incidents_list if i.status not in ("Resolved", "Closed"))
    critical_incidents_count = sum(
        1 for i in all_incidents_list if i.severity in ("High", "Critical") and i.status not in ("Resolved", "Closed")
    )

    # --- Sessions KPI: simple real count ---
    total_sessions = Session.query.count()

    # --- Intelligence Engine integration: reuses the exact same
    # pipeline already built and verified for /intelligence — not a
    # second implementation. Wrapped defensively so a problem here
    # (e.g. a transient DB hiccup) degrades gracefully instead of
    # breaking the whole dashboard. ---
    try:
        active_alerts, intel_snapshot = intelligence_engine.run_intelligence_cycle(
            db, Attendee, Venue, Session, Sponsor, Incident, IntelligenceAlert, has_session_conflict
        )
        intelligence_available = True
    except Exception:
        active_alerts, intel_snapshot = [], None
        intelligence_available = False

    critical_alerts_count = sum(1 for a in active_alerts if a.severity == "Critical")
    warning_alerts_count = sum(1 for a in active_alerts if a.severity == "Warning")
    total_active_alerts = len(active_alerts)

    # --- Venue utilization: average real occupancy across sessions
    # that actually have a venue assigned, reusing the Intelligence
    # Engine's own per-session occupancy calculation rather than a
    # second copy of the same math. ---
    if intel_snapshot and intel_snapshot["session_occupancy"]:
        occ_values = [o["occupancy_pct"] for o in intel_snapshot["session_occupancy"]]
        avg_venue_utilization = round(sum(occ_values) / len(occ_values), 1)
        # Chart data for the Venue Utilization by Session panel — capped
        # to the 8 highest-occupancy sessions so the chart stays readable.
        sorted_occ = sorted(intel_snapshot["session_occupancy"], key=lambda o: -o["occupancy_pct"])[:8]
        intel_session_labels = [o["session"].title for o in sorted_occ]
        intel_session_util_values = [o["occupancy_pct"] for o in sorted_occ]
    else:
        avg_venue_utilization = None
        intel_session_labels, intel_session_util_values = [], []

    # --- Event Health: a single, real, decision-support status,
    # deliberately derived from the SAME alerts the Intelligence Engine
    # already detected — not a separate, disconnected scoring system.
    # Critical alert present -> At Risk. Warning only -> Needs Attention.
    # Nothing active -> Healthy. ---
    if not intelligence_available:
        event_health = {"status": "Unknown", "color": "slate", "detail": "Intelligence Engine unavailable right now."}
    elif critical_alerts_count > 0:
        event_health = {"status": "At Risk", "color": "danger", "detail": f"{critical_alerts_count} critical issue(s) need immediate attention."}
    elif warning_alerts_count > 0:
        event_health = {"status": "Needs Attention", "color": "warning", "detail": f"{warning_alerts_count} warning(s) currently active."}
    else:
        event_health = {"status": "Healthy", "color": "success", "detail": "No active risks detected across the event."}

    # --- Executive-level alert summary: top 3 only (Critical first),
    # each with its real recommendation. Full list stays on /intelligence. ---
    severity_order = {"Critical": 0, "Warning": 1, "Informational": 2}
    top_alerts = sorted(active_alerts, key=lambda a: severity_order.get(a.severity, 3))[:3]

    # ============================================================
    # AI Insights panel (existing panel, extended) — condensed,
    # single-item versions of health/risk/action/trend. Deliberately
    # NOT a second copy of the Executive Alerts list above or the
    # full /intelligence page — just the single most important item
    # of each kind, reusing data already computed above.
    # ============================================================
    top_risk_alert = top_alerts[0] if top_alerts else None

    # Condensed version specifically for the compact AI Insights card —
    # the full, untruncated recommendation is still shown in full on the
    # Executive Alerts panel and the /intelligence page. This is purely
    # a display concern for this one small card, not a data change.
    if top_risk_alert and top_risk_alert.recommendation:
        _rec = top_risk_alert.recommendation.strip()
        top_risk_recommendation_short = (_rec[:90].rsplit(" ", 1)[0] + "…") if len(_rec) > 90 else _rec
    else:
        top_risk_recommendation_short = None

    # Real registration velocity numbers, already computed inside
    # intel_snapshot by the Intelligence Engine — not recalculated here.
    if intel_snapshot:
        reg_pace_current = intel_snapshot["current_window_registrations"]
        reg_pace_previous = intel_snapshot["previous_window_registrations"]
    else:
        reg_pace_current, reg_pace_previous = 0, 0

    if reg_pace_current > reg_pace_previous:
        reg_pace_direction = "up"
    elif reg_pace_current < reg_pace_previous:
        reg_pace_direction = "down"
    else:
        reg_pace_direction = "flat"

    return render_template(
        "dashboard.html",
        event_info=EVENT_INFO,
        remaining_slots=max(EVENT_INFO["capacity"] - total, 0),
        total=total,
        registered=registered,
        checked_in=checked_in,
        checked_out=checked_out,
        inside=inside,
        attendees=attendees,
        top_city=top_city,
        top_gender=top_gender,
        avg_age=avg_age,
        trend_labels=trend_labels,
        trend_values=trend_values,
        gender_labels=gender_labels,
        gender_values=gender_values,
        state_labels=state_labels,
        state_values=state_values,
        # --- new executive data ---
        attendance_rate=attendance_rate,
        checkin_trend_labels=checkin_trend_labels,
        checkin_trend_values=checkin_trend_values,
        total_sponsors=total_sponsors,
        avg_sponsor_score=avg_sponsor_score,
        sponsor_status_counts=dict(sponsor_status_counts),
        open_incidents_count=open_incidents_count,
        critical_incidents_count=critical_incidents_count,
        total_sessions=total_sessions,
        intelligence_available=intelligence_available,
        total_active_alerts=total_active_alerts,
        critical_alerts_count=critical_alerts_count,
        warning_alerts_count=warning_alerts_count,
        avg_venue_utilization=avg_venue_utilization,
        intel_session_labels=intel_session_labels,
        intel_session_util_values=intel_session_util_values,
        event_health=event_health,
        top_alerts=top_alerts,
        top_risk_alert=top_risk_alert,
        top_risk_recommendation_short=top_risk_recommendation_short,
        reg_pace_current=reg_pace_current,
        reg_pace_previous=reg_pace_previous,
        reg_pace_direction=reg_pace_direction,
    )


@app.route("/attendees")
@login_required
def attendees():
    attendees = Attendee.query.all()
    return render_template("attendees.html", attendees=attendees)


@app.route("/checkin/<int:id>")
@login_required
def checkin(id):
    attendee = Attendee.query.get(id)
    attendee.status = "Checked In"
    attendee.check_in_time = datetime.utcnow()
    db.session.commit()
    return redirect("/attendees")


@app.route("/checkout/<int:id>")
@login_required
def checkout(id):
    attendee = Attendee.query.get(id)
    attendee.status = "Checked Out"
    attendee.check_out_time = datetime.utcnow()
    db.session.commit()
    return redirect("/attendees")


# ============================================================
# ATTENDEE-SIDE CHECK-IN / CHECK-OUT / SPONSOR INTERACTIONS
# No attendee login system exists in this project, so the attendee
# is identified purely by their numeric Attendee id in the URL —
# the same id already shown to them on success.html after registering.
# ============================================================
def sponsors_relevant_to_attendee(attendee):
    """
    Real sponsors only — never every sponsor in the system. A sponsor is
    relevant to this attendee if it's tied to the attendee's own
    registered session directly, or to the whole event that session
    belongs to (if any). No event/session on the attendee at all means
    no sponsors are shown, rather than falling back to "show everyone".
    """
    if not attendee.session_id or not attendee.session:
        return []

    session_obj = attendee.session
    conditions = [Sponsor.session_id == attendee.session_id]
    if session_obj.event_id:
        conditions.append(Sponsor.event_id == session_obj.event_id)

    return Sponsor.query.filter(db.or_(*conditions)).order_by(Sponsor.company_name).all()


@app.route("/attendee/<int:attendee_id>/status")
def attendee_status(attendee_id):
    attendee = Attendee.query.get_or_404(attendee_id)

    relevant_sponsors = sponsors_relevant_to_attendee(attendee)

    # Which (sponsor_id, interaction_type) combinations this attendee has
    # already logged, so the template can show "already recorded" instead
    # of letting the same interaction be logged over and over.
    existing = SponsorInteraction.query.filter_by(attendee_id=attendee.id).all()
    logged_types_by_sponsor = {}
    for i in existing:
        logged_types_by_sponsor.setdefault(i.sponsor_id, set()).add(i.interaction_type)

    return render_template(
        "attendee_status.html",
        attendee=attendee,
        event_info=EVENT_INFO,
        relevant_sponsors=relevant_sponsors,
        logged_types_by_sponsor=logged_types_by_sponsor,
        interaction_types=INTERACTION_TYPES,
    )


@app.route("/attendee/<int:attendee_id>/sponsors/<int:sponsor_id>/interact", methods=["POST"])
def record_sponsor_interaction(attendee_id, sponsor_id):
    attendee = Attendee.query.get_or_404(attendee_id)
    sponsor = Sponsor.query.get_or_404(sponsor_id)

    interaction_type = request.form.get("interaction_type", "").strip()
    if interaction_type not in INTERACTION_TYPES:
        flash("Invalid interaction type.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    # Server-side relevance check — never trust that the sponsor shown to
    # this attendee client-side wasn't tampered with. The sponsor must
    # genuinely be tied to this attendee's own session or its event.
    if sponsor not in sponsors_relevant_to_attendee(attendee):
        flash("This sponsor is not associated with your session.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    # Duplicate prevention: the same attendee logging the same interaction
    # type with the same sponsor more than once doesn't inflate the count.
    already_logged = SponsorInteraction.query.filter_by(
        attendee_id=attendee.id, sponsor_id=sponsor.id, interaction_type=interaction_type
    ).first()
    if already_logged:
        flash(f"You've already recorded a {interaction_type.lower()} with {sponsor.company_name}.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    db.session.add(SponsorInteraction(
        sponsor_id=sponsor.id,
        attendee_id=attendee.id,
        session_id=attendee.session_id,
        interaction_type=interaction_type,
        timestamp=datetime.utcnow(),
    ))
    db.session.commit()

    flash(f"{interaction_type} recorded with {sponsor.company_name}.", "success")
    return redirect(url_for("attendee_status", attendee_id=attendee.id))


@app.route("/attendee/<int:attendee_id>/checkin", methods=["POST"])
def attendee_checkin(attendee_id):
    attendee = Attendee.query.get_or_404(attendee_id)

    if attendee.status != "Registered":
        flash("You have already checked in.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    attendee.status = "Checked In"
    attendee.check_in_time = datetime.utcnow()
    db.session.commit()

    flash("You have successfully checked in.", "success")
    return redirect(url_for("attendee_status", attendee_id=attendee.id))


@app.route("/attendee/<int:attendee_id>/checkout", methods=["POST"])
def attendee_checkout(attendee_id):
    attendee = Attendee.query.get_or_404(attendee_id)

    if attendee.status == "Registered":
        flash("You must check in before you can check out.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    if attendee.status == "Checked Out":
        flash("You have already checked out.", "error")
        return redirect(url_for("attendee_status", attendee_id=attendee.id))

    attendee.status = "Checked Out"
    attendee.check_out_time = datetime.utcnow()
    db.session.commit()

    flash("You have successfully checked out.", "success")
    return redirect(url_for("attendee_status", attendee_id=attendee.id))


@app.route("/analytics")
@login_required
def analytics():
    total = Attendee.query.count()
    registered = Attendee.query.filter_by(status="Registered").count()
    checked_in = Attendee.query.filter_by(status="Checked In").count()
    checked_out = Attendee.query.filter_by(status="Checked Out").count()

    attendees = Attendee.query.all()

    gender_counts = Counter(a.gender for a in attendees if a.gender)
    city_counts = Counter(a.city for a in attendees if a.city)

    return render_template(
        "analytics.html",
        total=total,
        registered=registered,
        checked_in=checked_in,
        checked_out=checked_out,
        gender_labels=list(gender_counts.keys()),
        gender_values=list(gender_counts.values()),
        city_labels=list(city_counts.keys()),
        city_values=list(city_counts.values())
    )


@app.route("/ai_insights")
@login_required
def ai_insights():
    attendees = Attendee.query.all()
    total = len(attendees)

    if total == 0:
        return render_template("ai_insights.html", insights=None, recommendations=[])

    interest_counts = Counter(a.interest for a in attendees if a.interest)
    city_counts = Counter(a.city for a in attendees if a.city)
    gender_counts = Counter(a.gender for a in attendees if a.gender)
    org_counts = Counter(a.organization for a in attendees if a.organization)
    designation_counts = Counter(a.designation for a in attendees if a.designation)
    date_counts = Counter(a.registration_time.date() for a in attendees if a.registration_time)

    top_interest = interest_counts.most_common(1)[0][0] if interest_counts else "N/A"
    top_city = city_counts.most_common(1)[0][0] if city_counts else "N/A"
    top_org = org_counts.most_common(1)[0][0] if org_counts else "N/A"
    top_designation = designation_counts.most_common(1)[0][0] if designation_counts else "N/A"

    ages = [a.age for a in attendees if a.age]
    avg_age = round(sum(ages) / len(ages), 1) if ages else 0

    male_count = gender_counts.get("Male", 0)
    female_count = gender_counts.get("Female", 0)
    male_pct = round((male_count / total) * 100, 1)
    female_pct = round((female_count / total) * 100, 1)

    checked_in = sum(1 for a in attendees if a.status == "Checked In")
    checked_out = sum(1 for a in attendees if a.status == "Checked Out")
    checked_in_pct = round((checked_in / total) * 100, 1)
    checked_out_pct = round((checked_out / total) * 100, 1)

    num_days = len(date_counts) if date_counts else 1
    avg_per_day = round(total / num_days, 1)
    peak_day, _ = date_counts.most_common(1)[0] if date_counts else (None, 0)
    peak_day_str = peak_day.strftime("%d %b %Y") if peak_day else "N/A"

    insights = {
        "total": total,
        "avg_age": avg_age,
        "checked_in_pct": checked_in_pct,
        "checked_out_pct": checked_out_pct,
        "top_interest": top_interest,
        "top_city": top_city,
        "male_pct": male_pct,
        "female_pct": female_pct,
        "top_org": top_org,
        "top_designation": top_designation,
        "avg_per_day": avg_per_day,
        "peak_day": peak_day_str,
        "most_active_interest": top_interest,
        "top_5_cities": city_counts.most_common(5),
    }

    recommendations = []
    recommendations.append(f"{top_interest} is the most popular interest area — consider increasing workshop capacity for it.")
    if checked_in_pct > 70:
        recommendations.append(f"{checked_in_pct}% of attendees are currently checked in — consider opening another help desk.")
    recommendations.append(f"Most registrations are coming from {top_city} — consider planning more events there.")
    cloud_pct = round((interest_counts.get("Cloud Computing", 0) / total) * 100, 1)
    if cloud_pct < 10:
        recommendations.append("Cloud Computing registrations are low — consider promoting Cloud sessions more actively.")
    if avg_age < 25:
        recommendations.append(f"Average attendee age is {avg_age} — consider adding beginner-friendly workshops.")
    if female_pct < 30:
        recommendations.append(f"Only {female_pct}% of attendees are female — consider outreach to improve diversity.")

    fallback = [
        f"Peak registrations were recorded on {peak_day_str} — plan staffing accordingly.",
        f"The most common organisation is {top_org} — consider a tailored networking session.",
        f"Average registrations per day currently stand at {avg_per_day}.",
    ]
    for fb in fallback:
        if len(recommendations) >= 6:
            break
        recommendations.append(fb)
    recommendations = recommendations[:6]

    return render_template("ai_insights.html", insights=insights, recommendations=recommendations)


# ============================================================
# MILESTONE 2 — Venue Agent
# ============================================================
from datetime import datetime as dt

# NOTE: The standalone venue-booking system (VenueBooking-based) has been
# retired in favour of Sessions, which are now the only place an actual
# venue assignment happens (Session.venue_id + has_session_conflict()).
# The VenueBooking table and its historical data are kept intact (used by
# compute_venue_insights() below for existing metrics), but no new
# VenueBooking rows can be created any more since /venues/<id>/book and
# /venues/booking/<id>/edit were removed along with the Book button.


# ============================================================
# Venue Recommendation Engine — transparent, rule-based, no external AI
# ============================================================
EVENT_TYPE_VENUE_TYPE_HINTS = {
    "conference": ["conference hall", "auditorium", "convention centre"],
    "seminar": ["seminar hall", "conference hall"],
    "workshop": ["seminar hall", "conference hall"],
    "exhibition": ["exhibition hall", "convention centre"],
    "wedding": ["hotel ballroom"],
    "reception": ["hotel ballroom"],
    "product launch": ["auditorium", "convention centre", "hotel ballroom"],
    "meetup": ["conference hall", "seminar hall"],
}


def parse_facilities(text):
    if not text:
        return []
    return [f.strip() for f in text.split(",") if f.strip()]


def score_venue(venue, attendees, location, event_type, facilities_required, budget):
    """
    Returns a dict with a transparent 0-100 score and the reasoning behind it.
    Weighting (adds up to 100):
      Capacity fit  -> 40 pts   (tighter fit to attendee count = higher score)
      Location      -> 20 pts   (exact match only; neutral/full if not specified)
      Facilities    -> 20 pts   (proportional to how many required facilities are present)
      Availability  -> 10 pts   (unavailable venues score 0 here)
      Budget        -> 10 pts   (neutral/full if no budget given)
    Event type is NOT scored — it's only used for an informational note,
    since it wasn't part of the 5 scoring factors requested.
    """
    venue_facilities = [f.strip().lower() for f in (venue.facilities or "").split(",") if f.strip()]

    # --- Capacity (40 pts) ---
    capacity_ratio = (attendees / venue.capacity) if venue.capacity else 0
    capacity_score = 40 * min(capacity_ratio, 1.0)

    # --- Location (20 pts) ---
    if location:
        location_match = venue.location.strip().lower() == location.strip().lower()
        location_score = 20 if location_match else 0
    else:
        location_match = None
        location_score = 20

    # --- Facilities (20 pts) ---
    matched, missing = [], []
    for rf in facilities_required:
        (matched if rf.lower() in venue_facilities else missing).append(rf)
    facilities_score = (20 * (len(matched) / len(facilities_required))) if facilities_required else 20

    # --- Availability (10 pts) ---
    availability_score = 10 if venue.availability else 0

    # --- Budget (10 pts) ---
    if budget is not None:
        within_budget = venue.cost <= budget
        budget_score = 10 if within_budget else 0
    else:
        within_budget = None
        budget_score = 10

    total_score = round(min(max(capacity_score + location_score + facilities_score
                                 + availability_score + budget_score, 0), 100))

    # --- Human-readable reasons (list of (is_positive, text)) ---
    reasons = []
    if capacity_ratio >= 0.6:
        reasons.append((True, f"Suitable capacity ({venue.capacity} seats for {attendees} attendees)"))
    else:
        reasons.append((True, f"Capacity available, but larger than needed ({venue.capacity} seats for {attendees} attendees)"))

    if location:
        reasons.append((True, f"Location matches your preference ({venue.location})") if location_match
                        else (False, f"Different location ({venue.location}, requested {location})"))

    if facilities_required:
        if not missing:
            reasons.append((True, f"All required facilities available ({', '.join(matched)})"))
        elif matched:
            reasons.append((False, f"Missing facilities: {', '.join(missing)}"))
        else:
            reasons.append((False, "None of the required facilities are available"))

    if venue.availability:
        reasons.append((True, "Currently available"))
    else:
        reason_text = "Currently unavailable" + (f" — {venue.unavailable_reason}" if venue.unavailable_reason else "")
        reasons.append((False, reason_text))

    if budget is not None:
        reasons.append((True, f"Within your budget (₹{venue.cost:,.0f} ≤ ₹{budget:,.0f})") if within_budget
                        else (False, f"Exceeds your budget (₹{venue.cost:,.0f} > ₹{budget:,.0f})"))

    # Informational only — does not affect score
    if event_type:
        hints = EVENT_TYPE_VENUE_TYPE_HINTS.get(event_type.strip().lower())
        if hints and venue.venue_type and venue.venue_type.strip().lower() in hints:
            reasons.append((True, f"Venue type ({venue.venue_type}) suits a {event_type} event"))

    return {
        "venue": venue,
        "score": total_score,
        "reasons": reasons,
        "matched_facilities": matched,
        "missing_facilities": missing,
    }


# ============================================================
# Venue Insights — calculated live from Venue + VenueBooking, no hardcoded values
# ============================================================
def compute_venue_insights():
    all_venues = Venue.query.all()
    all_bookings = VenueBooking.query.all()

    total_venues = len(all_venues)
    available_count = sum(1 for v in all_venues if v.availability)
    unavailable_count = total_venues - available_count
    avg_capacity = round(sum(v.capacity for v in all_venues) / total_venues, 1) if total_venues else 0
    total_bookings = len(all_bookings)

    insights = {
        "total_venues": total_venues,
        "available_count": available_count,
        "unavailable_count": unavailable_count,
        "avg_capacity": avg_capacity,
        "total_bookings": total_bookings,
        "has_bookings": total_bookings > 0,
        "most_booked_venue": None,
        "most_booked_count": None,
        "most_popular_location": None,
        "most_popular_type": None,
        "avg_booking_cost": None,
        "utilization_pct": 0,
        "most_common_day": None,
        "peak_period": None,
    }

    if total_bookings == 0:
        return insights

    venue_booking_counts = Counter(b.venue_id for b in all_bookings)
    most_booked_id, most_booked_count = venue_booking_counts.most_common(1)[0]
    most_booked_venue_obj = Venue.query.get(most_booked_id)

    location_counts = Counter(b.venue.location for b in all_bookings if b.venue)
    type_counts = Counter(b.venue.venue_type for b in all_bookings if b.venue and b.venue.venue_type)
    booking_costs = [b.venue.cost for b in all_bookings if b.venue]

    distinct_booked_venues = len(venue_booking_counts)
    utilization_pct = round((distinct_booked_venues / total_venues) * 100, 1) if total_venues else 0

    # Needs a few data points before a "most common day" claim is meaningful
    most_common_day = None
    if total_bookings >= 3:
        day_counts = Counter(b.booking_date.strftime("%A") for b in all_bookings)
        most_common_day = day_counts.most_common(1)[0][0]

    # Peak time-of-day period — only among bookings that actually have a start_time
    timed_bookings = [b for b in all_bookings if b.start_time]
    peak_period = None
    if len(timed_bookings) >= 3:
        def bucket(t):
            if t.hour < 12:
                return "Morning"
            if t.hour < 17:
                return "Afternoon"
            return "Evening"
        period_counts = Counter(bucket(b.start_time) for b in timed_bookings)
        peak_period = period_counts.most_common(1)[0][0]

    insights.update({
        "most_booked_venue": most_booked_venue_obj.name if most_booked_venue_obj else None,
        "most_booked_count": most_booked_count,
        "most_popular_location": location_counts.most_common(1)[0][0] if location_counts else None,
        "most_popular_type": type_counts.most_common(1)[0][0] if type_counts else None,
        "avg_booking_cost": round(sum(booking_costs) / len(booking_costs), 2) if booking_costs else None,
        "utilization_pct": utilization_pct,
        "most_common_day": most_common_day,
        "peak_period": peak_period,
    })
    return insights


@app.route("/venues")
@login_required
def venues():
    name_query = request.args.get("name", "").strip()
    min_capacity = request.args.get("min_capacity", "").strip()

    query = Venue.query
    if name_query:
        query = query.filter(Venue.name.ilike(f"%{name_query}%"))

    min_capacity_val = None
    if min_capacity:
        try:
            min_capacity_val = int(min_capacity)
            query = query.filter(Venue.capacity >= min_capacity_val)
        except ValueError:
            flash("Capacity must be a number.", "error")

    if min_capacity_val is not None:
        # Rank by closest capacity fit first: since every result already
        # satisfies capacity >= min_capacity_val, sorting capacity ascending
        # puts the smallest sufficient venue (the tightest fit) first.
        all_venues = query.order_by(Venue.capacity.asc()).all()
    else:
        all_venues = query.order_by(Venue.name).all()

    # ---- Venue Recommendation Engine (only runs if the recommend form was submitted) ----
    rec_attendees = request.args.get("rec_attendees", "").strip()
    rec_location = request.args.get("rec_location", "").strip()
    rec_event_type = request.args.get("rec_event_type", "").strip()
    rec_facilities = request.args.get("rec_facilities", "").strip()
    rec_budget = request.args.get("rec_budget", "").strip()

    recommendations = None

    if rec_attendees:
        attendees_val = None
        try:
            attendees_val = int(rec_attendees)
            if attendees_val <= 0:
                raise ValueError
        except ValueError:
            flash("Expected number of attendees must be a positive whole number.", "error")

        budget_val = None
        budget_invalid = False
        if attendees_val and rec_budget:
            try:
                budget_val = float(rec_budget)
                if budget_val < 0:
                    raise ValueError
            except ValueError:
                flash("Maximum budget must be a valid number.", "error")
                budget_invalid = True

        if attendees_val and not budget_invalid:
            facilities_list = parse_facilities(rec_facilities)
            candidate_venues = Venue.query.filter(Venue.capacity >= attendees_val).all()

            if not candidate_venues:
                flash(f"No venues have enough capacity for {attendees_val} attendees.", "error")
            else:
                scored = [
                    score_venue(v, attendees_val, rec_location, rec_event_type, facilities_list, budget_val)
                    for v in candidate_venues
                ]
                # Available venues always rank above unavailable ones, regardless of score
                scored.sort(key=lambda r: (not r["venue"].availability, -r["score"]))
                recommendations = scored[:3]

    venue_insights = compute_venue_insights()

    return render_template(
        "venues.html",
        venues=all_venues,
        name_query=name_query,
        min_capacity=min_capacity,
        recommendations=recommendations,
        rec_attendees=rec_attendees,
        rec_location=rec_location,
        rec_event_type=rec_event_type,
        rec_facilities=rec_facilities,
        rec_budget=rec_budget,
        venue_insights=venue_insights,
    )


@app.route("/venues/add", methods=["POST"])
@login_required
def add_venue():
    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    capacity_str = request.form.get("capacity", "").strip()
    venue_type = request.form.get("venue_type", "").strip()
    facilities = request.form.get("facilities", "").strip()
    cost_str = request.form.get("cost", "").strip()
    availability = request.form.get("availability") == "yes"
    unavailable_reason = request.form.get("unavailable_reason", "").strip()

    if not name or not location or not capacity_str or not cost_str:
        flash("Name, location, capacity and cost are required.", "error")
        return redirect(url_for("venues"))

    try:
        capacity = int(capacity_str)
        if capacity <= 0:
            raise ValueError
    except ValueError:
        flash("Capacity must be a positive whole number.", "error")
        return redirect(url_for("venues"))

    try:
        cost = float(cost_str)
        if cost < 0:
            raise ValueError
    except ValueError:
        flash("Cost must be a valid number.", "error")
        return redirect(url_for("venues"))

    existing = Venue.query.filter_by(name=name, location=location).first()
    if existing:
        flash(f"A venue named '{name}' already exists in {location}.", "error")
        return redirect(url_for("venues"))

    new_venue = Venue(
        name=name,
        location=location,
        capacity=capacity,
        venue_type=venue_type or None,
        facilities=facilities or None,
        cost=cost,
        availability=availability,
        # A reason only makes sense for an unavailable venue — if the
        # organizer marked it Available, any reason text is ignored.
        unavailable_reason=(unavailable_reason or None) if not availability else None
    )
    db.session.add(new_venue)
    db.session.commit()

    flash(f"Venue '{name}' added successfully.", "success")
    return redirect(url_for("venues"))


@app.route("/venues/<int:venue_id>/edit", methods=["POST"])
@login_required
def edit_venue(venue_id):
    venue = Venue.query.get_or_404(venue_id)

    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    capacity_str = request.form.get("capacity", "").strip()
    venue_type = request.form.get("venue_type", "").strip()
    facilities = request.form.get("facilities", "").strip()
    cost_str = request.form.get("cost", "").strip()
    availability = request.form.get("availability") == "yes"
    unavailable_reason = request.form.get("unavailable_reason", "").strip()

    if not name or not location or not capacity_str or not cost_str:
        flash("Name, location, capacity and cost are required.", "error")
        return redirect(url_for("venues"))

    try:
        capacity = int(capacity_str)
        if capacity <= 0:
            raise ValueError
    except ValueError:
        flash("Capacity must be a positive whole number.", "error")
        return redirect(url_for("venues"))

    try:
        cost = float(cost_str)
        if cost < 0:
            raise ValueError
    except ValueError:
        flash("Cost must be a valid number.", "error")
        return redirect(url_for("venues"))

    # Duplicate check, excluding this venue's own current row
    duplicate = Venue.query.filter(
        Venue.name == name, Venue.location == location, Venue.id != venue_id
    ).first()
    if duplicate:
        flash(f"Another venue named '{name}' already exists in {location}.", "error")
        return redirect(url_for("venues"))

    venue.name = name
    venue.location = location
    venue.capacity = capacity
    venue.venue_type = venue_type or None
    venue.facilities = facilities or None
    venue.cost = cost
    venue.availability = availability
    # Changing back to Available clears any old reason automatically
    venue.unavailable_reason = (unavailable_reason or None) if not availability else None

    db.session.commit()
    flash(f"Venue '{name}' updated successfully.", "success")
    return redirect(url_for("venues"))


@app.route("/speakers")
@login_required
def speakers():
    search_query = request.args.get("q", "").strip()

    query = Speaker.query
    if search_query:
        # "Search by name or expertise" — matches either field
        query = query.filter(
            db.or_(
                Speaker.name.ilike(f"%{search_query}%"),
                Speaker.expertise.ilike(f"%{search_query}%"),
            )
        )

    all_speakers = query.order_by(Speaker.name).all()
    return render_template("speakers.html", speakers=all_speakers, search_query=search_query)


@app.route("/speakers/add", methods=["POST"])
@login_required
def add_speaker():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    organization = request.form.get("organization", "").strip()
    designation = request.form.get("designation", "").strip()
    expertise = request.form.get("expertise", "").strip()
    session_duration_str = request.form.get("session_duration", "").strip()
    availability = request.form.get("availability") == "yes"

    if not name or not email or not expertise:
        flash("Name, email and expertise are required.", "error")
        return redirect(url_for("speakers"))

    existing = Speaker.query.filter_by(email=email).first()
    if existing:
        flash(f"A speaker with the email '{email}' already exists.", "error")
        return redirect(url_for("speakers"))

    session_duration = None
    if session_duration_str:
        try:
            session_duration = int(session_duration_str)
            if session_duration <= 0:
                raise ValueError
        except ValueError:
            flash("Session duration must be a positive whole number (minutes).", "error")
            return redirect(url_for("speakers"))

    new_speaker = Speaker(
        name=name,
        email=email,
        organization=organization or None,
        designation=designation or None,
        expertise=expertise,
        availability=availability,
        session_duration=session_duration,
    )
    db.session.add(new_speaker)
    db.session.commit()

    flash(f"Speaker '{name}' added successfully.", "success")
    return redirect(url_for("speakers"))


@app.route("/speakers/<int:speaker_id>/edit", methods=["POST"])
@login_required
def edit_speaker(speaker_id):
    speaker = Speaker.query.get_or_404(speaker_id)

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    organization = request.form.get("organization", "").strip()
    designation = request.form.get("designation", "").strip()
    expertise = request.form.get("expertise", "").strip()
    session_duration_str = request.form.get("session_duration", "").strip()
    availability = request.form.get("availability") == "yes"

    if not name or not email or not expertise:
        flash("Name, email and expertise are required.", "error")
        return redirect(url_for("speakers"))

    duplicate = Speaker.query.filter(
        Speaker.email == email, Speaker.id != speaker_id
    ).first()
    if duplicate:
        flash(f"Another speaker with the email '{email}' already exists.", "error")
        return redirect(url_for("speakers"))

    session_duration = None
    if session_duration_str:
        try:
            session_duration = int(session_duration_str)
            if session_duration <= 0:
                raise ValueError
        except ValueError:
            flash("Session duration must be a positive whole number (minutes).", "error")
            return redirect(url_for("speakers"))

    speaker.name = name
    speaker.email = email
    speaker.organization = organization or None
    speaker.designation = designation or None
    speaker.expertise = expertise
    speaker.availability = availability
    speaker.session_duration = session_duration

    db.session.commit()
    flash(f"Speaker '{name}' updated successfully.", "success")
    return redirect(url_for("speakers"))


# ============================================================
# MILESTONE 2 — Session Management (Step 2)
# ============================================================
def parse_time_flexible(time_str):
    """
    Accepts time strings in either HH:MM (what <input type="time"> submits)
    or HH:MM:SS (what a Python time object stringifies to, e.g. if it ever
    ends up unformatted somewhere upstream). Returns a datetime.time.
    Raises ValueError if neither format matches.
    """
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.strptime(time_str, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized time format: {time_str}")


def has_session_conflict(session_date, start_time, end_time, venue_id=None, speaker_id=None, exclude_session_id=None):
    """
    Checks for venue and speaker scheduling conflicts on the same date.
    Two sessions conflict when: new_start < existing_end AND new_end > existing_start.
    Returns an error message string if a conflict is found, otherwise None.

    Cancelled sessions are excluded from this check entirely — a
    cancelled session no longer actually occupies its venue or its
    speaker's time, so it must not block that slot for anyone else.
    This is the single source of truth for both venue and speaker
    availability (see the speaker recommendation scoring below, which
    reuses this exact function), so fixing it here fixes both at once.
    """
    base_query = Session.query.filter(Session.date == session_date, Session.status != "Cancelled")
    if exclude_session_id:
        base_query = base_query.filter(Session.id != exclude_session_id)

    def overlaps(existing):
        return start_time < existing.end_time and end_time > existing.start_time

    if venue_id:
        for existing in base_query.filter(Session.venue_id == venue_id).all():
            if overlaps(existing):
                venue_obj = Venue.query.get(venue_id)
                venue_name = venue_obj.name if venue_obj else "This venue"
                return (f"Venue conflict: {venue_name} is already booked from "
                        f"{existing.start_time.strftime('%H:%M')} to "
                        f"{existing.end_time.strftime('%H:%M')} on this date.")

    if speaker_id:
        for existing in base_query.filter(Session.speaker_id == speaker_id).all():
            if overlaps(existing):
                speaker_obj = Speaker.query.get(speaker_id)
                speaker_name = speaker_obj.name if speaker_obj else "This speaker"
                return (f"Speaker conflict: {speaker_name} is already assigned to another "
                        f"session from {existing.start_time.strftime('%H:%M')} to "
                        f"{existing.end_time.strftime('%H:%M')}.")

    return None


# ============================================================
# MILESTONE 2 — Speaker Recommendation (Session module)
# Transparent rule-based scoring, no external AI/ML.
# Weighting: Expertise match 50% + Topic relevance 20% + Availability 30%
# (When no required_expertise is given, that 50% shifts onto topic
# relevance instead, so the score stays on a 100-point scale either way.)
# ============================================================
_STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "into", "your", "about", "session"}

# Small, transparent alias table — NOT machine learning, just a lookup so common
# abbreviations used across this app's own data (Speaker.expertise, Attendee.interest)
# are recognized as equivalent. Without this, "AI/ML" and "Artificial Intelligence"
# share no substring and would incorrectly score as unrelated.
_EXPERTISE_ALIASES = {
    "ai": "artificial intelligence machine learning",
    "ml": "artificial intelligence machine learning",
    "ai/ml": "artificial intelligence machine learning",
    "artificial intelligence": "artificial intelligence machine learning",
    "machine learning": "artificial intelligence machine learning",
    "artificial intelligence & machine learning": "artificial intelligence machine learning",
    "devops": "development operations",
    "iot": "internet of things",
    "internet of things (iot)": "internet of things",
    "ui/ux": "user interface experience design",
    "ui/ux design": "user interface experience design",
    "ux": "user interface experience design",
    "ui": "user interface experience design",
}


def _normalize_term(term):
    t = term.strip().lower()
    return _EXPERTISE_ALIASES.get(t, t)


def _keywords(text):
    return {
        w.strip(".,()&:;").lower()
        for w in (text or "").split()
        if len(w) > 3 and w.strip(".,()&:;").lower() not in _STOPWORDS
    }


def score_speaker_for_session(speaker, title, required_terms, session_date, start_time, end_time, exclude_session_id=None):
    speaker_expertise_terms = [t.strip().lower() for t in (speaker.expertise or "").split(",") if t.strip()]
    speaker_norm_terms = [_normalize_term(t) for t in speaker_expertise_terms]

    # --- Expertise match (50 pts, or 0 if no expertise was required) ---
    matched_terms = []
    if required_terms:
        for rt in required_terms:
            rt_norm = _normalize_term(rt)
            if any(rt_norm in se or se in rt_norm for se in speaker_norm_terms):
                matched_terms.append(rt)
        expertise_ratio = len(matched_terms) / len(required_terms)
        expertise_weight, topic_weight = 50, 20
    else:
        expertise_ratio = 0
        expertise_weight, topic_weight = 0, 70  # shift expertise's weight onto topic relevance

    # --- Topic relevance (20 pts normally, 70 pts if expertise wasn't specified) ---
    title_words = _keywords(title)
    expertise_words = set()
    for term in speaker_expertise_terms:
        expertise_words |= _keywords(term)
    topic_ratio = (len(title_words & expertise_words) / len(title_words)) if (title_words and expertise_words) else 0

    # --- Availability (30 pts) — reuses the SAME conflict function used by add/edit session ---
    conflict_message = has_session_conflict(
        session_date, start_time, end_time,
        venue_id=None, speaker_id=speaker.id, exclude_session_id=exclude_session_id
    )
    schedule_available = conflict_message is None
    available = bool(speaker.availability) and schedule_available
    availability_score = 30 if available else 0

    total_score = round(min(max(
        (expertise_weight * expertise_ratio) + (topic_weight * topic_ratio) + availability_score,
        0), 100))

    # --- Is this speaker even worth showing? ---
    if required_terms:
        relevant = bool(matched_terms) or topic_ratio > 0
    else:
        relevant = True

    # --- Reason (built from the actual computed factors, not a fixed string per speaker) ---
    if not available:
        reason = "Marked unavailable in speaker profile" if not speaker.availability \
            else "Already assigned to another session at this time"
    elif required_terms and len(matched_terms) == len(required_terms):
        reason = "Strong expertise match for this session"
    elif required_terms and matched_terms:
        reason = f"Partial expertise match ({len(matched_terms)}/{len(required_terms)} required areas)"
    elif topic_ratio > 0.3:
        reason = "Good topic match with session title"
    elif required_terms:
        reason = "Limited expertise overlap with this session"
    else:
        reason = "Available, but limited topic signal to rank against"

    return {
        "id": speaker.id,
        "name": speaker.name,
        "expertise": speaker.expertise,
        "available": available,
        "score": total_score,
        "reason": reason,
        "relevant": relevant,
    }


@app.route("/sessions/recommend_speaker")
@login_required
def recommend_speaker():
    title = request.args.get("title", "").strip()
    required_expertise = request.args.get("required_expertise", "").strip()
    date_str = request.args.get("date", "").strip()
    start_time_str = request.args.get("start_time", "").strip()
    end_time_str = request.args.get("end_time", "").strip()
    exclude_session_id_str = request.args.get("exclude_session_id", "").strip()

    if not date_str or not start_time_str or not end_time_str:
        return jsonify({"error": "Date, start time and end time are required to check availability."}), 400

    try:
        session_date = dt.strptime(date_str, "%Y-%m-%d").date()
        start_time = parse_time_flexible(start_time_str)
        end_time = parse_time_flexible(end_time_str)
    except ValueError:
        return jsonify({"error": "Invalid date or time format."}), 400

    if start_time >= end_time:
        return jsonify({"error": "Start time must be before end time."}), 400

    exclude_session_id = int(exclude_session_id_str) if exclude_session_id_str.isdigit() else None
    required_terms = [t.strip() for t in required_expertise.split(",") if t.strip()]

    scored = [
        score_speaker_for_session(sp, title, required_terms, session_date, start_time, end_time, exclude_session_id)
        for sp in Speaker.query.all()
    ]
    scored = [r for r in scored if r["relevant"]]
    scored.sort(key=lambda r: -r["score"])
    top = scored[:5]

    return jsonify({
        "recommendations": top,
        "no_candidates": len(scored) == 0,
        "all_unavailable": len(scored) > 0 and not any(r["available"] for r in scored),
    })


def parse_session_form(form):
    """Shared parsing/validation for add and edit session forms.
    Returns (data_dict, error_message). data_dict is None if error_message is set."""
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    date_str = form.get("date", "").strip()
    start_time_str = form.get("start_time", "").strip()
    end_time_str = form.get("end_time", "").strip()
    venue_id_str = form.get("venue_id", "").strip()
    speaker_id_str = form.get("speaker_id", "").strip()
    required_expertise = form.get("required_expertise", "").strip()
    status = form.get("status", "Scheduled").strip() or "Scheduled"

    if not title or not date_str or not start_time_str or not end_time_str:
        return None, "Title, date, start time and end time are required."

    try:
        session_date = dt.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None, "Invalid date format."

    try:
        start_time = parse_time_flexible(start_time_str)
        end_time = parse_time_flexible(end_time_str)
    except ValueError:
        return None, "Invalid time format."

    if start_time >= end_time:
        return None, "Start time must be before end time."

    venue_id = None
    if venue_id_str:
        venue_obj = Venue.query.get(venue_id_str)
        if not venue_obj:
            return None, "Selected venue does not exist."
        venue_id = venue_obj.id

    speaker_id = None
    if speaker_id_str:
        speaker_obj = Speaker.query.get(speaker_id_str)
        if not speaker_obj:
            return None, "Selected speaker does not exist."
        speaker_id = speaker_obj.id

    return {
        "title": title,
        "description": description or None,
        "date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "venue_id": venue_id,
        "speaker_id": speaker_id,
        "required_expertise": required_expertise or None,
        "status": status,
    }, None


# ============================================================
# MILESTONE 2 — Session Analytics (Sessions page, bottom section)
# Calculated live from the existing Session table. No new model,
# no hardcoded values, no separate route/template.
# ============================================================
def _session_duration_hours(s):
    dummy_date = dt(2000, 1, 1)
    start = dt.combine(dummy_date, s.start_time)
    end = dt.combine(dummy_date, s.end_time)
    return (end - start).total_seconds() / 3600


def compute_session_analytics():
    all_sessions = Session.query.all()
    total_sessions = len(all_sessions)

    if total_sessions == 0:
        return {"has_data": False}

    scheduled_count = sum(1 for s in all_sessions if s.status == "Scheduled")

    # Cancelled sessions don't count toward hours/duration/venue/speaker/topic
    # breakdowns — a cancelled session isn't actually occupying a time slot
    # any more, even though the row still exists for record-keeping.
    active_sessions = [s for s in all_sessions if s.status != "Cancelled"]

    total_hours = sum(_session_duration_hours(s) for s in active_sessions)
    avg_hours = (total_hours / len(active_sessions)) if active_sessions else 0

    venue_counts = Counter(s.venue.name for s in active_sessions if s.venue)
    speaker_counts = Counter(s.speaker.name for s in active_sessions if s.speaker)
    # "Topic" maps to Session.required_expertise — the closest existing field
    # to the topic categories (e.g. "AI/ML", "Cloud Computing") already used
    # elsewhere in the app; sessions have no separate topic/category field.
    topic_counts = Counter(s.required_expertise for s in active_sessions if s.required_expertise)

    def as_bars(counter, limit=5):
        top = counter.most_common(limit)
        max_count = top[0][1] if top else 1
        return [{"label": label, "count": count, "pct": round((count / max_count) * 100)} for label, count in top]

    return {
        "has_data": True,
        "total_sessions": total_sessions,
        "scheduled_count": scheduled_count,
        "total_hours": round(total_hours, 1),
        "avg_hours": round(avg_hours, 1),
        "most_used_venue": venue_counts.most_common(1)[0][0] if venue_counts else "N/A",
        "top_speaker": speaker_counts.most_common(1)[0][0] if speaker_counts else "N/A",
        "by_venue": as_bars(venue_counts),
        "by_speaker": as_bars(speaker_counts),
        "by_topic": as_bars(topic_counts),
    }


@app.route("/sessions")
@login_required
def sessions():
    search_query = request.args.get("q", "").strip()

    query = Session.query
    if search_query:
        # "Search by title/topic" — matches either field
        query = query.filter(
            db.or_(
                Session.title.ilike(f"%{search_query}%"),
                Session.description.ilike(f"%{search_query}%"),
            )
        )

    all_sessions = query.order_by(Session.date, Session.start_time).all()
    all_venues = Venue.query.order_by(Venue.name).all()
    all_speakers = Speaker.query.order_by(Speaker.name).all()

    # Analytics are always computed from the FULL, unfiltered session set —
    # not the search-filtered "all_sessions" above — so typing in the search
    # box never changes the analytics numbers.
    session_analytics = compute_session_analytics()

    return render_template(
        "sessions.html",
        sessions=all_sessions,
        venues=all_venues,
        speakers=all_speakers,
        search_query=search_query,
        session_analytics=session_analytics,
    )


@app.route("/sessions/add", methods=["POST"])
@login_required
def add_session():
    data, error = parse_session_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("sessions"))

    conflict_message = has_session_conflict(
        data["date"], data["start_time"], data["end_time"],
        venue_id=data["venue_id"], speaker_id=data["speaker_id"]
    )
    if conflict_message:
        flash(conflict_message, "error")
        return redirect(url_for("sessions"))

    new_session = Session(**data)
    db.session.add(new_session)
    db.session.commit()

    email_sent = None  # None = not applicable (no speaker assigned), True = sent, False = failed
    if new_session.speaker_id and new_session.speaker and new_session.speaker.email:
        try:
            send_speaker_schedule_email(new_session.speaker, new_session, mode="confirmation")
            email_sent = True
        except Exception as e:
            print(f"Speaker confirmation email failed: {e}")
            email_sent = False

    if email_sent is True:
        flash(f"Session '{data['title']}' created successfully. Speaker confirmation email sent.", "success")
    elif email_sent is False:
        flash(f"Session '{data['title']}' created successfully, but the speaker email could not be sent.", "success")
    else:
        flash(f"Session '{data['title']}' created successfully.", "success")

    return redirect(url_for("sessions"))


@app.route("/sessions/<int:session_id>/edit", methods=["POST"])
@login_required
def edit_session(session_id):
    session_obj = Session.query.get_or_404(session_id)

    data, error = parse_session_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("sessions"))

    conflict_message = has_session_conflict(
        data["date"], data["start_time"], data["end_time"],
        venue_id=data["venue_id"], speaker_id=data["speaker_id"],
        exclude_session_id=session_obj.id
    )
    if conflict_message:
        flash(conflict_message, "error")
        return redirect(url_for("sessions"))

    # Capture old state BEFORE overwriting, so we know what actually changed
    # and can still notify whoever was the speaker before this edit.
    old_speaker_id = session_obj.speaker_id
    old_speaker_obj = session_obj.speaker
    old_values = {
        "title": session_obj.title,
        "description": session_obj.description,
        "date": session_obj.date,
        "start_time": session_obj.start_time,
        "end_time": session_obj.end_time,
        "venue_id": session_obj.venue_id,
        "required_expertise": session_obj.required_expertise,
    }

    session_obj.title = data["title"]
    session_obj.description = data["description"]
    session_obj.date = data["date"]
    session_obj.start_time = data["start_time"]
    session_obj.end_time = data["end_time"]
    session_obj.venue_id = data["venue_id"]
    session_obj.speaker_id = data["speaker_id"]
    session_obj.required_expertise = data["required_expertise"]
    session_obj.status = data["status"]

    db.session.commit()

    speaker_changed = old_speaker_id != data["speaker_id"]
    details_changed = any(old_values[k] != data[k] for k in old_values)
    new_speaker = session_obj.speaker  # re-fetched fresh post-commit (session state expires on commit)

    email_sent = None  # None = not applicable, True = sent, False = failed

    if speaker_changed:
        if new_speaker and new_speaker.email:
            try:
                send_speaker_schedule_email(new_speaker, session_obj, mode="confirmation")
                email_sent = True
            except Exception as e:
                print(f"Speaker confirmation email failed: {e}")
                email_sent = False
    elif details_changed and new_speaker and new_speaker.email:
        try:
            send_speaker_schedule_email(new_speaker, session_obj, mode="update")
            email_sent = True
        except Exception as e:
            print(f"Speaker update email failed: {e}")
            email_sent = False

    # Best-effort notice to whoever was replaced — logged on failure, but
    # doesn't change the main flash message, to keep it simple and readable.
    if speaker_changed and old_speaker_obj and old_speaker_obj.email:
        try:
            send_speaker_schedule_email(old_speaker_obj, session_obj, mode="cancellation")
        except Exception as e:
            print(f"Reassignment notice to previous speaker failed: {e}")

    if email_sent is True:
        flash(f"Session '{data['title']}' updated successfully. Speaker confirmation email sent.", "success")
    elif email_sent is False:
        flash(f"Session '{data['title']}' updated successfully, but the speaker email could not be sent.", "success")
    else:
        flash(f"Session '{data['title']}' updated successfully.", "success")

    return redirect(url_for("sessions"))


@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
@login_required
def delete_session(session_id):
    session_obj = Session.query.get_or_404(session_id)
    title = session_obj.title

    # A hard delete has no attendee-facing workflow behind it at all —
    # it would silently leave every registered attendee's session_id
    # pointing at a session that no longer exists, with no incident,
    # no alert, and no chance to notify them. Cancel already handles
    # all of that properly via the orchestrator, so route people there
    # instead of allowing a silent, unrecoverable data gap.
    attendee_count = Attendee.query.filter_by(session_id=session_id).count()
    if attendee_count > 0:
        flash(
            f"Cannot delete '{title}' — {attendee_count} attendee(s) are still registered to it. "
            f"Use Cancel Session instead so they're properly identified and notified.",
            "error",
        )
        return redirect(url_for("sessions"))

    db.session.delete(session_obj)
    db.session.commit()
    flash(f"Session '{title}' deleted.", "success")
    return redirect(url_for("sessions"))


# ============================================================
# MILESTONE 3 — Sponsor Management (Task 1: foundation)
# ============================================================
SPONSOR_PACKAGES = ["Platinum", "Gold", "Silver", "Custom"]
SPONSOR_CONTRACT_STATUSES = ["Pending", "Signed", "Cancelled"]
SPONSOR_OVERALL_STATUSES = ["Active", "Confirmed", "Completed", "Cancelled"]
DELIVERABLE_STATUSES = ["Pending", "In Progress", "Completed"]
INTERACTION_TYPES = ["Booth Visit", "Lead Generated", "Attendee Interaction"]


def events_for_dropdown():
    """
    Source of truth for the Sponsor Event dropdown: the Session table,
    exactly as the Registration page's `available_sessions` query does.
    Event.query.all() is never called here.

    Steps (matching the required behavior exactly):
      1. Look at existing Session records.
      2. Get the distinct event_id values from those Session records.
      3. From those event_ids, load ONLY the corresponding Event records.
      4. Return that list — an event with zero Session rows pointing to
         it can never appear here, no matter how many rows exist in the
         Event table.
    """
    distinct_event_ids = [
        row[0] for row in
        db.session.query(Session.event_id)
        .filter(Session.event_id.isnot(None))
        .distinct()
        .all()
    ]

    if not distinct_event_ids:
        return []

    return (
        Event.query
        .filter(Event.id.in_(distinct_event_ids))
        .order_by(Event.name)
        .all()
    )


def parse_sponsor_form(form):
    """Shared parsing/validation for add and edit sponsor forms.
    Returns (data_dict, error_message). data_dict is None if error_message is set."""
    company_name = form.get("company_name", "").strip()
    contact_person = form.get("contact_person", "").strip()
    email = form.get("email", "").strip()
    phone = form.get("phone", "").strip()
    package = form.get("package", "").strip()
    total_amount_str = form.get("total_amount", "").strip()
    amount_paid_str = form.get("amount_paid", "").strip()
    contract_status = form.get("contract_status", "Pending").strip() or "Pending"
    overall_status = form.get("overall_status", "Active").strip() or "Active"
    event_id_str = form.get("event_id", "").strip()

    if not company_name or not contact_person or not email or not package:
        return None, "Company name, contact person, email and package are required."

    if package not in SPONSOR_PACKAGES:
        return None, "Please select a valid sponsorship package."

    try:
        total_amount = float(total_amount_str) if total_amount_str else 0.0
        if total_amount < 0:
            raise ValueError
    except ValueError:
        return None, "Total amount must be a valid, non-negative number."

    try:
        amount_paid = float(amount_paid_str) if amount_paid_str else 0.0
        if amount_paid < 0:
            raise ValueError
    except ValueError:
        return None, "Amount paid must be a valid, non-negative number."

    if amount_paid > total_amount:
        return None, "Amount paid cannot exceed the total amount."

    event_id = None
    if event_id_str:
        try:
            eid = int(event_id_str)
            if not Event.query.get(eid):
                return None, "Selected event does not exist."
            event_id = eid
        except ValueError:
            return None, "Invalid event selection."

    session_id = None
    session_id_str = form.get("session_id", "").strip()
    if session_id_str:
        try:
            sid = int(session_id_str)
            if not Session.query.get(sid):
                return None, "Selected session does not exist."
            session_id = sid
        except ValueError:
            return None, "Invalid session selection."

    return {
        "company_name": company_name,
        "contact_person": contact_person,
        "email": email,
        "phone": phone or None,
        "package": package,
        "total_amount": total_amount,
        "amount_paid": amount_paid,
        "contract_status": contract_status,
        "overall_status": overall_status,
        "event_id": event_id,
        "session_id": session_id,
    }, None


@app.route("/sponsors")
@login_required
def sponsors():
    event_filter_str = request.args.get("event_id", "").strip()
    event_filter_id = int(event_filter_str) if event_filter_str.isdigit() else None

    query = Sponsor.query
    if event_filter_id:
        query = query.filter(Sponsor.event_id == event_filter_id)
    all_sponsors = query.order_by(Sponsor.company_name).all()

    all_events = events_for_dropdown()

    # Session field: ALL existing sessions, always available — same source
    # and same "plain full list" pattern already used for Venue/Speaker in
    # Session Management. Deliberately NOT filtered by event and NOT gated
    # behind selecting an event first, since most sessions have no event_id
    # set at all and still need to be linkable to a sponsor.
    all_sessions = Session.query.order_by(Session.date, Session.start_time).all()

    return render_template(
        "sponsors.html",
        sponsors=all_sponsors,
        packages=SPONSOR_PACKAGES,
        contract_statuses=SPONSOR_CONTRACT_STATUSES,
        overall_statuses=SPONSOR_OVERALL_STATUSES,
        events=all_events,
        event_filter_id=event_filter_id,
        all_sessions=all_sessions,
    )


@app.route("/sponsors/add", methods=["POST"])
@login_required
def add_sponsor():
    data, error = parse_sponsor_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("sponsors"))

    db.session.add(Sponsor(**data))
    db.session.commit()

    flash(f"Sponsor '{data['company_name']}' added successfully.", "success")
    return redirect(url_for("sponsors"))


@app.route("/sponsors/<int:sponsor_id>/edit", methods=["POST"])
@login_required
def edit_sponsor(sponsor_id):
    sponsor = Sponsor.query.get_or_404(sponsor_id)

    data, error = parse_sponsor_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("sponsors"))

    sponsor.company_name = data["company_name"]
    sponsor.contact_person = data["contact_person"]
    sponsor.email = data["email"]
    sponsor.phone = data["phone"]
    sponsor.package = data["package"]
    sponsor.total_amount = data["total_amount"]
    sponsor.amount_paid = data["amount_paid"]
    sponsor.contract_status = data["contract_status"]
    sponsor.overall_status = data["overall_status"]
    sponsor.event_id = data["event_id"]
    sponsor.session_id = data["session_id"]

    db.session.commit()
    flash(f"Sponsor '{data['company_name']}' updated successfully.", "success")
    return redirect(url_for("sponsors"))


@app.route("/sponsors/<int:sponsor_id>/delete", methods=["POST"])
@login_required
def delete_sponsor(sponsor_id):
    sponsor = Sponsor.query.get_or_404(sponsor_id)
    name = sponsor.company_name
    db.session.delete(sponsor)
    db.session.commit()
    flash(f"Sponsor '{name}' deleted.", "success")
    return redirect(url_for("sponsors"))


# ============================================================
# MILESTONE 3 — Sponsor Deliverable Tracking (Task 2)
# ============================================================
@app.route("/sponsors/<int:sponsor_id>/view")
@login_required
def view_sponsor(sponsor_id):
    sponsor = Sponsor.query.get_or_404(sponsor_id)
    deliverables = (SponsorDeliverable.query
                    .filter_by(sponsor_id=sponsor_id)
                    .order_by(SponsorDeliverable.due_date, SponsorDeliverable.id)
                    .all())
    total = len(deliverables)
    completed = sum(1 for d in deliverables if d.status == "Completed")

    interactions = (SponsorInteraction.query
                     .filter_by(sponsor_id=sponsor_id)
                     .order_by(SponsorInteraction.timestamp.desc())
                     .all())

    return render_template(
        "sponsor_detail.html",
        sponsor=sponsor,
        deliverables=deliverables,
        total_deliverables=total,
        completed_deliverables=completed,
        deliverable_statuses=DELIVERABLE_STATUSES,
        packages=SPONSOR_PACKAGES,
        contract_statuses=SPONSOR_CONTRACT_STATUSES,
        overall_statuses=SPONSOR_OVERALL_STATUSES,
        interactions=interactions,
    )


@app.route("/sponsors/<int:sponsor_id>/deliverables/add", methods=["POST"])
@login_required
def add_deliverable(sponsor_id):
    Sponsor.query.get_or_404(sponsor_id)
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    due_date_str = request.form.get("due_date", "").strip()
    status = request.form.get("status", "Pending").strip()

    if not name:
        flash("Deliverable name is required.", "error")
        return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))

    due_date = None
    if due_date_str:
        try:
            due_date = dt.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid due date.", "error")
            return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))

    if status not in DELIVERABLE_STATUSES:
        status = "Pending"

    db.session.add(SponsorDeliverable(
        sponsor_id=sponsor_id,
        name=name,
        description=description or None,
        due_date=due_date,
        status=status,
    ))
    db.session.commit()
    flash(f"Deliverable '{name}' added.", "success")
    return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))


@app.route("/sponsors/<int:sponsor_id>/deliverables/<int:deliverable_id>/edit", methods=["POST"])
@login_required
def edit_deliverable(sponsor_id, deliverable_id):
    deliverable = SponsorDeliverable.query.filter_by(id=deliverable_id, sponsor_id=sponsor_id).first_or_404()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    due_date_str = request.form.get("due_date", "").strip()
    status = request.form.get("status", "Pending").strip()

    if not name:
        flash("Deliverable name is required.", "error")
        return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))

    due_date = None
    if due_date_str:
        try:
            due_date = dt.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid due date.", "error")
            return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))

    if status not in DELIVERABLE_STATUSES:
        status = "Pending"

    deliverable.name = name
    deliverable.description = description or None
    deliverable.due_date = due_date
    deliverable.status = status
    db.session.commit()
    flash(f"Deliverable '{name}' updated.", "success")
    return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))


@app.route("/sponsors/<int:sponsor_id>/deliverables/<int:deliverable_id>/delete", methods=["POST"])
@login_required
def delete_deliverable(sponsor_id, deliverable_id):
    deliverable = SponsorDeliverable.query.filter_by(id=deliverable_id, sponsor_id=sponsor_id).first_or_404()
    name = deliverable.name
    db.session.delete(deliverable)
    db.session.commit()
    flash(f"Deliverable '{name}' deleted.", "success")
    return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))


@app.route("/sponsors/<int:sponsor_id>/deliverables/<int:deliverable_id>/complete", methods=["POST"])
@login_required
def complete_deliverable(sponsor_id, deliverable_id):
    deliverable = SponsorDeliverable.query.filter_by(id=deliverable_id, sponsor_id=sponsor_id).first_or_404()
    deliverable.status = "Completed"
    db.session.commit()
    flash(f"'{deliverable.name}' marked as completed.", "success")
    return redirect(url_for("view_sponsor", sponsor_id=sponsor_id))


# ============================================================
# MILESTONE 3 — Sponsor Performance Tracking (Task 3)
#
# Score weights: delivery 40% + payment 40% + engagement 20%
# Engagement = Leads (real SponsorInteraction rows, type "Lead
# Generated") ÷ attendees registered for the sponsor's own Event
# (or specific Session, if the sponsor has one) — never the whole
# system's attendee count, and never a manually-typed number.
# If the sponsor has no scoped attendees yet, engagement component
# is treated as 50 (neutral) so sponsors aren't unfairly penalised
# for missing attendance data.
# Status thresholds: Excellent >= 65, Good >= 30, At Risk < 30
# ============================================================
def compute_sponsor_performance(event_id=None):
    query = Sponsor.query
    if event_id:
        query = query.filter(Sponsor.event_id == event_id)
    sponsors = query.order_by(Sponsor.company_name).all()

    has_scoped_data = False
    results = []
    for sponsor in sponsors:
        # --- Deliverable completion (unchanged) ---
        total_del = len(sponsor.deliverables)
        completed_del = sum(1 for d in sponsor.deliverables if d.status == "Completed")
        delivery_pct = round((completed_del / total_del) * 100) if total_del > 0 else 0

        # --- Payment progress (unchanged) ---
        payment_pct = round((sponsor.amount_paid / sponsor.total_amount) * 100) if sponsor.total_amount > 0 else 0

        # --- Scope: this sponsor's specific session if set, else every
        # session under its whole event. No event/session at all -> no
        # valid scope, so nothing can legitimately count toward this
        # sponsor yet. SponsorInteraction has no event_id column of its
        # own — Event is only ever reached via session.event, so "the
        # sponsor's whole event" is expressed here as "all of that
        # event's session ids", same real-world scope as before. ---
        if sponsor.session_id:
            relevant_session_ids = [sponsor.session_id]
            scoped_attendee_count = sponsor.registered_attendee_count or 0
        elif sponsor.event_id and sponsor.event:
            relevant_session_ids = [s.id for s in sponsor.event.sessions]
            scoped_attendee_count = sponsor.registered_attendee_count or 0
        else:
            relevant_session_ids = []
            scoped_attendee_count = 0

        interactions_query = SponsorInteraction.query.filter_by(sponsor_id=sponsor.id)
        if relevant_session_ids:
            interactions_query = interactions_query.filter(SponsorInteraction.session_id.in_(relevant_session_ids))
        else:
            interactions_query = interactions_query.filter(SponsorInteraction.id.is_(None))

        scoped_interactions = interactions_query.all()
        leads = sum(1 for i in scoped_interactions if i.interaction_type == "Lead Generated")
        booth_visits = sum(1 for i in scoped_interactions if i.interaction_type == "Booth Visit")
        attendee_interactions = sum(1 for i in scoped_interactions if i.interaction_type == "Attendee Interaction")

        if scoped_attendee_count > 0:
            has_scoped_data = True
            engagement_pct = round(min(leads / scoped_attendee_count, 1.0) * 100)
            engagement_component = engagement_pct
        else:
            engagement_pct = None          # displayed as "—" in template
            engagement_component = 50      # neutral — no scoped attendance data yet

        # --- Weighted overall score (0–100), same weights as before ---
        overall_score = round(
            delivery_pct * 0.40 +
            payment_pct  * 0.40 +
            engagement_component * 0.20
        )

        if overall_score >= 65:
            perf_status = "Excellent"
        elif overall_score >= 30:
            perf_status = "Good"
        else:
            perf_status = "At Risk"

        results.append({
            "sponsor": sponsor,
            "total_del": total_del,
            "completed_del": completed_del,
            "delivery_pct": delivery_pct,
            "payment_pct": payment_pct,
            "leads": leads,
            "booth_visits": booth_visits,
            "attendee_interactions": attendee_interactions,
            "engagement_pct": engagement_pct,
            "overall_score": overall_score,
            "perf_status": perf_status,
        })

    results.sort(key=lambda x: -x["overall_score"])
    return results, has_scoped_data


# ============================================================
# MILESTONE 3 — AI Sponsorship Insights
# Rule-based, generated entirely from the real numbers already
# computed by compute_sponsor_performance() — no external AI/LLM
# call, no new dependency, matching the same transparent pattern
# already used by AI Insights (attendee side) and the Venue/Speaker
# Recommendation engines elsewhere in this project. Nothing here
# is hardcoded per-sponsor; every sentence is built from real,
# already-computed values (score, leads, deliverables, payment).
# ============================================================
def generate_sponsor_insight(item):
    sponsor = item["sponsor"]
    delivery_pct = item["delivery_pct"]
    payment_pct = item["payment_pct"]
    engagement_pct = item["engagement_pct"]  # None if no scoped attendees exist yet
    leads = item["leads"]
    booth_visits = item["booth_visits"]
    attendee_interactions = item["attendee_interactions"]
    total_del = item["total_del"]
    completed_del = item["completed_del"]
    overall_score = item["overall_score"]
    perf_status = item["perf_status"]

    has_event_link = bool(sponsor.event_id or sponsor.session_id)
    has_deliverables = total_del > 0
    has_payment_data = sponsor.total_amount > 0
    has_engagement_data = engagement_pct is not None

    # --- Genuinely insufficient data: nothing real to say anything about ---
    if not has_event_link and not has_deliverables and not has_payment_data:
        return {
            "insufficient": True,
            "summary": f"Not enough data yet to generate a meaningful insight for {sponsor.company_name}.",
            "main_point": "No linked event/session, no deliverables, and no sponsorship amount recorded yet.",
            "action": "Link this sponsor to an event or session, add at least one deliverable, and record the sponsorship amount.",
            "caveats": [],
        }

    caveats = []
    if not has_engagement_data:
        caveats.append("engagement can't be assessed yet since no attendees are registered for this sponsor's linked event/session")
    if not has_deliverables:
        caveats.append("no deliverables have been added yet")
    if not has_payment_data:
        caveats.append("no sponsorship amount has been recorded yet")

    summary = f"{sponsor.company_name} is performing {perf_status.lower()} with an overall score of {overall_score}/100."

    # Only compare dimensions that actually have real data behind them.
    dimensions = []
    if has_payment_data:
        dimensions.append(("payment", payment_pct))
    if has_deliverables:
        dimensions.append(("delivery", delivery_pct))
    if has_engagement_data:
        dimensions.append(("engagement", engagement_pct))

    if perf_status == "Excellent":
        if dimensions:
            best_dim, best_val = max(dimensions, key=lambda d: d[1])
            main_point = f"Strongest area: {best_dim} at {best_val}%."
        else:
            main_point = "Overall score is strong."
        action = "Performing well — maintain current engagement and payment cadence."
    elif dimensions:
        worst_dim, worst_val = min(dimensions, key=lambda d: d[1])
        if worst_dim == "engagement":
            main_point = (
                f"Main issue: low engagement at {worst_val}% "
                f"({leads} lead(s), {booth_visits} booth visit(s), {attendee_interactions} attendee interaction(s) recorded)."
            )
            action = "Increase booth visibility and encourage more attendee interactions to generate leads."
        elif worst_dim == "delivery":
            pending_count = total_del - completed_del
            main_point = f"Main issue: {pending_count} of {total_del} deliverable(s) still pending ({worst_val}% complete)."
            action = f"Complete the {pending_count} pending deliverable(s)."
        else:  # payment
            main_point = f"Main issue: payment progress at {worst_val}% (\u20b9{sponsor.pending_amount:,.0f} pending)."
            action = f"Follow up on the pending payment of \u20b9{sponsor.pending_amount:,.0f}."
    else:
        main_point = "Not enough scored dimensions yet to identify a specific issue."
        action = "Add deliverables, payment details, and link this sponsor to an event or session."

    return {
        "insufficient": False,
        "summary": summary,
        "main_point": main_point,
        "action": action,
        "caveats": caveats,
    }


@app.route("/sponsors/performance")
@login_required
def sponsor_performance():
    event_filter_str = request.args.get("event_id", "").strip()
    event_filter_id  = int(event_filter_str) if event_filter_str.isdigit() else None

    all_events = events_for_dropdown()
    perf_data, has_scoped_data = compute_sponsor_performance(event_id=event_filter_id)

    # AI Insights are generated AFTER all real calculations are already
    # done, as a pure annotation step — compute_sponsor_performance()
    # itself is not modified in any way.
    for item in perf_data:
        item["ai_insight"] = generate_sponsor_insight(item)

    total_sponsors  = len(perf_data)
    excellent_count = sum(1 for p in perf_data if p["perf_status"] == "Excellent")
    good_count      = sum(1 for p in perf_data if p["perf_status"] == "Good")
    at_risk_count   = sum(1 for p in perf_data if p["perf_status"] == "At Risk")
    avg_score       = round(sum(p["overall_score"] for p in perf_data) / total_sponsors) if total_sponsors else 0

    return render_template(
        "sponsor_performance.html",
        perf_data=perf_data,
        total_sponsors=total_sponsors,
        excellent_count=excellent_count,
        good_count=good_count,
        at_risk_count=at_risk_count,
        avg_score=avg_score,
        has_scoped_data=has_scoped_data,
        events=all_events,
        event_filter_id=event_filter_id,
    )


# ============================================================
# MILESTONE 3 — Sponsor Analytical Report (Export)
#
# CSV via the same built-in csv/io approach already used for the
# Incident export — no new dependency. Reuses compute_sponsor_
# performance() exactly as it already exists; this route does not
# change or duplicate any performance/AI calculation, it only reads
# the same real result and writes it out as a file.
# ============================================================
@app.route("/sponsors/performance/export")
@login_required
def export_sponsor_report():
    event_filter_str = request.args.get("event_id", "").strip()
    event_filter_id = int(event_filter_str) if event_filter_str.isdigit() else None

    perf_data, _ = compute_sponsor_performance(event_id=event_filter_id)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Sponsor Performance Report - Generated {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}"])
    writer.writerow([])
    writer.writerow([
        "Sponsor", "Event", "Package", "Total Amount", "Paid Amount", "Pending Amount",
        "Leads", "Engagement %", "Deliverable Completion %", "Performance Score", "Performance Status",
    ])

    for item in perf_data:
        sponsor = item["sponsor"]
        writer.writerow([
            sponsor.company_name,
            sponsor.event.name if sponsor.event else "",
            sponsor.package,
            sponsor.total_amount,
            sponsor.amount_paid,
            sponsor.pending_amount,
            item["leads"],
            item["engagement_pct"] if item["engagement_pct"] is not None else "N/A",
            item["delivery_pct"],
            item["overall_score"],
            item["perf_status"],
        ])

    csv_data = output.getvalue()
    output.close()

    response = Response(csv_data, mimetype="text/csv")
    filename = f"sponsor_performance_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/sponsors/<int:sponsor_id>/update_leads", methods=["POST"])
@login_required
def update_leads(sponsor_id):
    sponsor = Sponsor.query.get_or_404(sponsor_id)
    leads_str = request.form.get("leads_count", "0").strip()
    try:
        leads = int(leads_str)
        if leads < 0:
            raise ValueError
    except ValueError:
        flash("Leads count must be a non-negative whole number.", "error")
        return redirect(url_for("sponsor_performance"))
    sponsor.leads_count = leads
    db.session.commit()
    flash(f"Leads updated for {sponsor.company_name}.", "success")
    return redirect(url_for("sponsor_performance"))


# ============================================================
# MILESTONE 3 — Incident Agent (basic Incident Management)
# ============================================================
INCIDENT_SEVERITIES = ["Low", "Medium", "High", "Critical"]

# Workflow — forward only, no skipping stages, no going backward.
# Status is never set directly from a free-choice dropdown; it only
# ever changes through the three transition routes below, each of
# which enforces its own precondition.
INCIDENT_STATUSES = ["Logged", "Investigating", "Resolved", "Closed"]
INCIDENT_CATEGORIES = ["Safety", "Medical", "Technical", "Security", "Logistics", "Other"]


def parse_incident_form(form):
    """Shared parsing/validation for add and edit incident forms.
    Deliberately does NOT touch status/escalation/resolution — those
    only ever change via their own dedicated routes further down.
    Returns (data_dict, error_message). data_dict is None if error_message is set."""
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "").strip()
    location = form.get("location", "").strip()
    severity = form.get("severity", "").strip()
    assigned_to = form.get("assigned_to", "").strip()
    contact_person = form.get("contact_person", "").strip()
    contact_phone = form.get("contact_phone", "").strip()
    alternate_contact = form.get("alternate_contact", "").strip()
    reported_time_str = form.get("reported_time", "").strip()

    if not title:
        return None, "Title is required."

    if severity not in INCIDENT_SEVERITIES:
        return None, "Please select a valid severity level."

    if reported_time_str:
        try:
            reported_time = dt.strptime(reported_time_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None, "Invalid reported time format."
    else:
        reported_time = datetime.utcnow()

    return {
        "title": title,
        "description": description or None,
        "category": category or None,
        "location": location or None,
        "reported_time": reported_time,
        "severity": severity,
        "assigned_to": assigned_to or None,
        "contact_person": contact_person or None,
        "contact_phone": contact_phone or None,
        "alternate_contact": alternate_contact or None,
    }, None


@app.route("/incidents")
@login_required
def incidents():
    all_incidents = Incident.query.order_by(Incident.reported_time.desc()).all()

    # ------------------------------------------------------------
    # Overview metrics — all computed from the same query above, no
    # extra DB round-trips. "Critical/High" and "Escalated" are scoped
    # to currently-active incidents (not Resolved/Closed) so this
    # reads as current operational load, not a lifetime total — the
    # same convention the workflow/escalation features already use.
    # ------------------------------------------------------------
    total_incidents = len(all_incidents)
    open_investigating_count = sum(1 for i in all_incidents if i.status in ("Logged", "Investigating"))
    critical_high_count = sum(
        1 for i in all_incidents
        if i.severity in ("Critical", "High") and i.status not in ("Resolved", "Closed")
    )
    escalated_count = sum(1 for i in all_incidents if i.is_escalated)
    resolved_closed_count = sum(1 for i in all_incidents if i.status in ("Resolved", "Closed"))

    # all_incidents is already ordered newest-first, so this is simply
    # the 5 most recent incidents that are still active.
    recent_active_incidents = [i for i in all_incidents if i.status not in ("Resolved", "Closed")][:5]

    # ------------------------------------------------------------
    # Event Operational Efficiency — average durations between real
    # workflow timestamps. Each pair is only included if both ends
    # exist and end >= start (same negative-duration guard already
    # used in the CSV report's resolution-time calculation, so an
    # incident whose reported_time was later edited to something
    # after a later timestamp can't silently skew these averages).
    # "No data" is shown rather than a fabricated number whenever
    # there isn't yet a single valid pair to average.
    # ------------------------------------------------------------
    def _avg_duration_hours(pairs):
        durations = [
            (end - start).total_seconds() / 3600.0
            for start, end in pairs
            if start and end and end >= start
        ]
        if not durations:
            return None
        return round(sum(durations) / len(durations), 1)

    avg_log_to_investigate_hours = _avg_duration_hours(
        [(i.reported_time, i.investigation_started_at) for i in all_incidents]
    )
    avg_investigate_to_resolve_hours = _avg_duration_hours(
        [(i.investigation_started_at, i.resolved_at) for i in all_incidents]
    )
    avg_total_resolution_hours = _avg_duration_hours(
        [(i.reported_time, i.resolved_at) for i in all_incidents]
    )

    return render_template(
        "incidents.html",
        incidents=all_incidents,
        severities=INCIDENT_SEVERITIES,
        categories=INCIDENT_CATEGORIES,
        total_incidents=total_incidents,
        open_investigating_count=open_investigating_count,
        critical_high_count=critical_high_count,
        escalated_count=escalated_count,
        resolved_closed_count=resolved_closed_count,
        recent_active_incidents=recent_active_incidents,
        avg_log_to_investigate_hours=avg_log_to_investigate_hours,
        avg_investigate_to_resolve_hours=avg_investigate_to_resolve_hours,
        avg_total_resolution_hours=avg_total_resolution_hours,
    )


# ============================================================
# MILESTONE 3 — Incident Analytical Reporting (Export)
#
# CSV via Python's built-in csv/io modules — no third-party library,
# since none is currently used anywhere in this project for reporting
# and none was needed here. Every number below is computed fresh from
# the real Incident table at request time; nothing is cached or
# hardcoded, so the export always reflects the database as it is the
# moment the button is clicked.
# ============================================================
@app.route("/incidents/export")
@login_required
def export_incidents_report():
    all_incidents = Incident.query.order_by(Incident.reported_time.desc()).all()
    total = len(all_incidents)

    severity_order = INCIDENT_SEVERITIES
    severity_counts = {s: 0 for s in severity_order}
    for i in all_incidents:
        if i.severity in severity_counts:
            severity_counts[i.severity] += 1

    priority_order = ["Low", "Medium", "High", "Urgent"]
    priority_counts = {p: 0 for p in priority_order}
    for i in all_incidents:
        if i.priority in priority_counts:
            priority_counts[i.priority] += 1

    status_order = ["Logged", "Investigating", "Resolved", "Closed"]
    status_counts = {s: 0 for s in status_order}
    for i in all_incidents:
        if i.status in status_counts:
            status_counts[i.status] += 1

    # Two distinct, real escalation numbers — not the same thing:
    # "currently active" uses the same is_escalated logic already
    # shown on the Incident Overview panel; "ever escalated" uses the
    # real, persisted `escalated` flag, which stays true even after
    # an incident is later resolved/closed.
    escalated_active_count = sum(1 for i in all_incidents if i.is_escalated)
    ever_escalated_count = sum(1 for i in all_incidents if i.escalated)

    resolved_count = sum(1 for i in all_incidents if i.status in ("Resolved", "Closed"))
    unresolved_count = total - resolved_count

    # Average resolution time, computed only from incidents that
    # actually have both a reported_time and a resolved_at — never
    # fabricated when there's nothing to average yet. Also guards
    # against a negative duration: reported_time can still be edited
    # after an incident is resolved (only status itself is protected),
    # so if it's ever edited to a value later than resolved_at, that
    # entry is excluded here rather than silently corrupting the
    # average with a nonsensical negative number.
    resolution_hours = [
        (i.resolved_at - i.reported_time).total_seconds() / 3600.0
        for i in all_incidents
        if i.resolved_at and i.reported_time and i.resolved_at >= i.reported_time
    ]
    if resolution_hours:
        avg_resolution_display = f"{round(sum(resolution_hours) / len(resolution_hours), 2)} hours"
    else:
        avg_resolution_display = "N/A - no resolved incidents yet"

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Incident Report - Generated {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}"])
    writer.writerow([])

    writer.writerow(["SUMMARY"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total Incidents", total])
    writer.writerow([])

    writer.writerow(["INCIDENTS BY SEVERITY"])
    writer.writerow(["Severity", "Count"])
    for sev in severity_order:
        writer.writerow([sev, severity_counts[sev]])
    writer.writerow([])

    writer.writerow(["INCIDENTS BY PRIORITY"])
    writer.writerow(["Priority", "Count"])
    for pr in priority_order:
        writer.writerow([pr, priority_counts[pr]])
    writer.writerow([])

    writer.writerow(["INCIDENTS BY STATUS"])
    writer.writerow(["Status", "Count"])
    for st in status_order:
        writer.writerow([st, status_counts[st]])
    writer.writerow([])

    writer.writerow(["ESCALATION"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Currently Escalated (active)", escalated_active_count])
    writer.writerow(["Ever Escalated", ever_escalated_count])
    writer.writerow([])

    writer.writerow(["RESOLUTION"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Average Resolution Time", avg_resolution_display])
    writer.writerow(["Resolved", resolved_count])
    writer.writerow(["Unresolved", unresolved_count])
    writer.writerow([])

    writer.writerow(["INCIDENT DETAILS"])
    writer.writerow(["Title", "Category", "Severity", "Priority", "Status", "Assigned To", "Reported Time", "Resolved Time"])
    for i in all_incidents:
        writer.writerow([
            i.title,
            i.category or "",
            i.severity,
            i.priority,
            i.status,
            i.assigned_to or "",
            i.reported_time.strftime("%Y-%m-%d %H:%M") if i.reported_time else "",
            i.resolved_at.strftime("%Y-%m-%d %H:%M") if i.resolved_at else "",
        ])

    csv_data = output.getvalue()
    output.close()

    response = Response(csv_data, mimetype="text/csv")
    filename = f"incident_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# ============================================================
# MILESTONE 3 — AI Incident Agent
# Rule-based, generated entirely from this incident's own real
# fields — no external AI/LLM call, no new dependency. Matches the
# exact same transparent pattern already used by AI Insights
# (attendee side) and AI Sponsorship Insights: plain Python logic
# reading real data, clearly labeled as such, never inventing a
# fact this incident doesn't actually have.
# ============================================================
# MILESTONE 3 — Incident Response Recommendations
#
# IMPORTANT: this project has no real AI/LLM integration anywhere —
# no API key, no external library, nothing to call. Rather than
# label this "AI" (misleading, since it isn't calling any model),
# this is named for what it actually is: a scenario-pattern-matching
# engine. It reads the incident's own title/description for known
# situation types (overcrowding, medical, fire, AV failure, security,
# etc.) and returns the practical playbook for that situation — not
# a repetition of the incident's own field values, and not a single
# generic "investigate immediately" line regardless of what happened.
# ============================================================
_INCIDENT_SCENARIOS = [
    {
        "keywords": ["overcrowd", "crowd", "queue", "congest", "bottleneck", "entrance", "entry"],
        "problem": "Attendee density has built up faster than the entry or flow point can process — most likely at a doorway, registration desk, or other single-point bottleneck.",
        "immediate": "Send additional staff or security to the location now to actively manage flow. Open an alternate entry or exit if one exists, and physically redirect attendees to spread density across more than one access point.",
        "next_steps": "Check whether a slowdown at registration/check-in is the actual root cause of the backup. Set up temporary queuing or barriers to organize the crowd, and give attendees a visible wait-time update so frustration doesn't build.",
        "escalation_trigger": "crowd density keeps growing despite the added staff, or attendees start showing signs of distress or agitation — this can turn into a real safety hazard quickly",
        "preventive": "For future events, model expected arrival rates against actual entry throughput, and stagger arrival times or add entry lanes accordingly.",
    },
    {
        "keywords": ["fire", "smoke", "burning smell", "burnt smell"],
        "problem": "A fire-safety-related event has been reported — a real fire, smoke, or a triggered alarm.",
        "immediate": "Verify the report directly with venue fire safety systems or staff right away — never assume it's a false alarm. Be ready to give evacuation guidance if needed.",
        "next_steps": "Follow the venue's fire safety protocol and contact the fire safety officer immediately. Activate the evacuation plan if the situation warrants it.",
        "escalation_trigger": "always, and immediately, regardless of the severity currently recorded — any real or suspected fire/smoke report needs the venue safety officer and possibly emergency services without delay",
        "preventive": "Confirm fire exits are clearly marked and unobstructed before doors open, and brief all staff on the evacuation procedure in advance.",
    },
    {
        "keywords": ["medical", "injur", "unwell", "fainted", "feels faint", "felt faint", "collaps", "unconscious", "bleeding", "sick", "seizure"],
        "problem": "An attendee is experiencing a medical issue that needs direct attention.",
        "immediate": "Send the on-site medical/first-aid team to the exact location immediately. Clear space around the person and do not move them if the injury looks serious.",
        "next_steps": "Record the attendee's details if not already known, and document what happened and when. Arrange transport to external medical care if on-site first aid isn't sufficient.",
        "escalation_trigger": "the situation goes beyond what on-site first aid can handle, or emergency services may be needed",
        "preventive": "Confirm first-aid stations are clearly signed and adequately staffed relative to expected attendance.",
    },
    {
        "keywords": ["projector", "microphone", " mic ", "audio", "sound system", " av ", "screen", "display", "wifi", "internet", "network down", "livestream", "live stream"],
        "problem": "A technical or AV equipment issue is disrupting a session or area.",
        "immediate": "Dispatch the AV/technical team to the location right away. Swap in a backup device if one is available, and let the speaker or session host know about the delay so they can adjust.",
        "next_steps": "Diagnose whether the fault is cabling, power, or the device itself. If it can't be fixed quickly, consider adjusting the session schedule or moving the session to a backup room.",
        "escalation_trigger": "the issue turns out to be building-wide (power or network), or on-site AV staff can't resolve it within a few minutes",
        "preventive": "Test all AV equipment before doors open, and keep backup units on hand for any session marked as critical.",
    },
    {
        "keywords": ["power outage", "power cut", "blackout", "no power", "electricity"],
        "problem": "A power outage is affecting some or all of the venue.",
        "immediate": "Check the actual scope of the outage — one room versus the whole building — and switch to backup lighting/power if it's available. Keep nearby attendees calm and informed.",
        "next_steps": "Contact venue facilities/electrical staff immediately, and assess whether affected sessions need to pause or relocate while power is restored.",
        "escalation_trigger": "the outage is building-wide, any safety system is affected, or it isn't resolved within a few minutes",
        "preventive": "Confirm the venue's backup power arrangements and emergency lighting coverage before the event.",
    },
    {
        "keywords": ["theft", "stolen", "altercation", "fight", "argument", "disturbance", "aggressive", "unauthorized", "trespass"],
        "problem": "A security-related incident involving conflict, theft, or unauthorized activity.",
        "immediate": "Alert on-site security to the exact location immediately. Keep any involved parties separated, and do not physically intervene personally.",
        "next_steps": "Document what happened — who, what, and when — for a security report, and check whether the area is covered by venue CCTV.",
        "escalation_trigger": "the situation involves aggression, theft, or unauthorized access of any kind — involve local authorities if needed",
        "preventive": "Review access control at every entry point and keep a visible security presence in high-traffic areas.",
    },
    {
        "keywords": ["lost item", "lost phone", "lost bag", "lost wallet", "missing person", "cant find", "can't find", "missing child"],
        "problem": "An attendee has lost a belonging, or is unable to locate someone in their group.",
        "immediate": "Direct them to the designated lost & found point. If this is a missing PERSON — especially a minor — treat it with real urgency and alert security immediately rather than waiting.",
        "next_steps": "Log the item's or person's details, and check with nearby staff or security who may have already seen them.",
        "escalation_trigger": "it involves a missing minor or a vulnerable person — a standard lost item rarely needs escalation on its own",
        "preventive": "Keep a clearly signed lost & found desk staffed, and brief all staff on the missing-person protocol in advance.",
    },
    {
        "keywords": ["food", "catering", "allergy", "allergic", "spoiled", "contamina"],
        "problem": "An issue with food or catering service, potentially involving an allergy concern.",
        "immediate": "Pull the affected food item from service immediately if there's any safety concern, and alert catering staff or the vendor right away.",
        "next_steps": "For allergy concerns, get details directly from the affected attendee and check the catering ingredient documentation. Arrange medical support if there's an active reaction.",
        "escalation_trigger": "there's any allergic reaction (escalate to the medical team) or a wider food safety concern (escalate to catering vendor management)",
        "preventive": "Confirm allergen labelling and the catering vendor's food-safety compliance ahead of the event.",
    },
    {
        "keywords": ["rain", "storm", "lightning", "weather", "wind"],
        "problem": "A weather condition is affecting the event, most likely an outdoor area.",
        "immediate": "Move affected attendees and equipment under cover, and pause any outdoor activity immediately if there's lightning or storm risk.",
        "next_steps": "Monitor weather updates continuously, and prepare or activate the indoor contingency space if one exists.",
        "escalation_trigger": "there's any lightning or severe storm risk to attendee safety",
        "preventive": "Have a weather contingency plan and active monitoring in place ahead of any outdoor event component.",
    },
]

# Used only when no scenario keyword matches the incident's own text —
# still tailored by real category, not a single one-size-fits-all line.
_CATEGORY_FALLBACK = {
    "Safety": {
        "problem": "A safety-related concern has been reported that doesn't match a more specific known pattern from its description.",
        "immediate": "Send a staff member to assess the situation on-site directly, and rope off or remove any visible immediate hazard.",
        "next_steps": "Get a first-hand account from whoever reported it or is nearest to it, and decide whether the area needs temporary closure.",
        "escalation_trigger": "there's any real risk to attendee safety, or the hazard can't be contained by on-site staff alone",
        "preventive": "Walk high-traffic areas periodically during the event to catch hazards before they get reported.",
    },
    "Medical": {
        "problem": "A medical concern has been reported.",
        "immediate": "Send the on-site first-aid team to assess the person directly, right away.",
        "next_steps": "Document symptoms and the timeline of what happened, and decide whether external medical help is needed.",
        "escalation_trigger": "the situation goes beyond what minor first aid can handle",
        "preventive": "Keep first-aid stations staffed and clearly signed throughout the event.",
    },
    "Technical": {
        "problem": "A technical issue has been reported that doesn't match a specific known equipment pattern from its description.",
        "immediate": "Send the technical team to the location to diagnose the fault directly.",
        "next_steps": "Determine whether it's isolated to one device/room or affects a wider system, and prepare a workaround if a time-sensitive session is affected.",
        "escalation_trigger": "it affects multiple rooms or sessions, or on-site staff can't resolve it quickly",
        "preventive": "Run a full technical check of every room before doors open.",
    },
    "Security": {
        "problem": "A security concern has been reported.",
        "immediate": "Alert on-site security to investigate the location in person immediately.",
        "next_steps": "Gather who/what/where details for a proper security report.",
        "escalation_trigger": "it involves any safety risk, conflict, or unauthorized access",
        "preventive": "Maintain visible security presence and clear access control at all entry points.",
    },
    "Logistics": {
        "problem": "A logistics or operational issue has been reported.",
        "immediate": "Send the operations team to assess and address the immediate disruption directly.",
        "next_steps": "Identify the root cause — supply, staffing, or scheduling — and coordinate a fix with the relevant vendor or team.",
        "escalation_trigger": "it's likely to affect the event schedule or attendee experience at scale",
        "preventive": "Build buffer time and backup suppliers into logistics planning for future events.",
    },
    "Other": {
        "problem": "An incident has been reported that doesn't match a more specific known category or pattern from its description.",
        "immediate": "Have a staff member assess the situation directly on-site to understand exactly what's involved before deciding next steps.",
        "next_steps": "Gather more detail from whoever reported it, then route it to the most relevant team once the nature of the issue is clear.",
        "escalation_trigger": "the situation affects attendee safety, attendee experience, or the event schedule",
        "preventive": "Encourage more detailed incident descriptions at the time of reporting, so the right team can respond faster next time.",
    },
}


def generate_incident_recommendation(incident):
    """
    Matches the incident's own title + description text against known
    scenario patterns (see _INCIDENT_SCENARIOS above). Falls back to a
    category-based playbook only if no scenario keyword is found in the
    actual text — never a single generic response regardless of content.
    Escalation guidance combines the scenario's own trigger condition
    with this incident's REAL current severity/escalated/status state.
    """
    text = f"{incident.title or ''} {incident.description or ''}".lower()

    matched_scenario = None
    for scenario in _INCIDENT_SCENARIOS:
        if any(kw in text for kw in scenario["keywords"]):
            matched_scenario = scenario
            break

    scenario_identified = matched_scenario is not None
    if not matched_scenario:
        matched_scenario = _CATEGORY_FALLBACK.get(incident.category, _CATEGORY_FALLBACK["Other"])

    # Escalation text: scenario-specific trigger + this incident's real state
    if incident.status in ("Resolved", "Closed"):
        escalation = f"This incident is already {incident.status} — for future reference, escalate when {matched_scenario['escalation_trigger']}."
    elif incident.escalated:
        escalation = f"Already escalated to {incident.escalated_to}. Continue escalating further if {matched_scenario['escalation_trigger']}."
    elif incident.severity == "Critical":
        escalation = f"Escalate now given the Critical severity — and in general, escalate when {matched_scenario['escalation_trigger']}."
    elif incident.severity == "High":
        escalation = f"Escalate promptly given the High severity — and in general, escalate when {matched_scenario['escalation_trigger']}."
    else:
        escalation = f"Escalate if {matched_scenario['escalation_trigger']}."

    return {
        "scenario_identified": scenario_identified,
        "problem": matched_scenario["problem"],
        "immediate_action": matched_scenario["immediate"],
        "next_steps": matched_scenario["next_steps"],
        "escalation": escalation,
        "preventive": matched_scenario["preventive"],
    }


@app.route("/incidents/<int:incident_id>/view")
@login_required
def view_incident(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    recommendation = generate_incident_recommendation(incident)
    return render_template("incident_detail.html", incident=incident, recommendation=recommendation)


@app.route("/incidents/add", methods=["POST"])
@login_required
def add_incident():
    data, error = parse_incident_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("incidents"))

    # New incidents always start at the beginning of the workflow —
    # this is not something the form can override.
    new_incident = Incident(status="Logged", **data)
    db.session.add(new_incident)
    db.session.commit()

    flash(f"Incident '{data['title']}' logged successfully.", "success")
    return redirect(url_for("incidents"))


@app.route("/incidents/<int:incident_id>/edit", methods=["POST"])
@login_required
def edit_incident(incident_id):
    incident = Incident.query.get_or_404(incident_id)

    data, error = parse_incident_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("incidents"))

    # Note: status is intentionally untouched here — it only changes
    # through the workflow transition routes below.
    incident.title = data["title"]
    incident.description = data["description"]
    incident.category = data["category"]
    incident.location = data["location"]
    incident.reported_time = data["reported_time"]
    incident.severity = data["severity"]
    incident.assigned_to = data["assigned_to"]
    incident.contact_person = data["contact_person"]
    incident.contact_phone = data["contact_phone"]
    incident.alternate_contact = data["alternate_contact"]

    db.session.commit()
    flash(f"Incident '{data['title']}' updated successfully.", "success")
    return redirect(url_for("incidents"))


@app.route("/incidents/<int:incident_id>/delete", methods=["POST"])
@login_required
def delete_incident(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    title = incident.title
    db.session.delete(incident)
    db.session.commit()
    flash(f"Incident '{title}' deleted.", "success")
    return redirect(url_for("incidents"))


# ------------------------------------------------------------
# Workflow transitions: Logged -> Investigating -> Resolved -> Closed
# Each route checks the incident's CURRENT status before doing
# anything — this is what makes skipping stages or moving backward
# impossible, regardless of what a form submission claims.
# ------------------------------------------------------------
@app.route("/incidents/<int:incident_id>/start_investigating", methods=["POST"])
@login_required
def start_investigating(incident_id):
    incident = Incident.query.get_or_404(incident_id)

    if incident.status != "Logged":
        flash(f"Cannot start investigating — incident is already '{incident.status}'.", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    incident.status = "Investigating"
    incident.investigation_started_at = datetime.utcnow()
    db.session.commit()

    flash(f"Incident '{incident.title}' moved to Investigating.", "success")
    return redirect(url_for("view_incident", incident_id=incident.id))


@app.route("/incidents/<int:incident_id>/mark_resolved", methods=["POST"])
@login_required
def mark_resolved(incident_id):
    incident = Incident.query.get_or_404(incident_id)

    if incident.status != "Investigating":
        flash(f"Cannot mark resolved — incident must be Investigating first (currently '{incident.status}').", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    resolution_notes = request.form.get("resolution_notes", "").strip()
    if not resolution_notes:
        flash("Resolution notes are required to mark an incident as Resolved.", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    resolved_by = request.form.get("resolved_by", "").strip()

    incident.status = "Resolved"
    incident.resolved_at = datetime.utcnow()
    incident.resolution_notes = resolution_notes
    incident.resolved_by = resolved_by or None
    db.session.commit()

    flash(f"Incident '{incident.title}' marked as Resolved.", "success")
    return redirect(url_for("view_incident", incident_id=incident.id))


@app.route("/incidents/<int:incident_id>/close", methods=["POST"])
@login_required
def close_incident(incident_id):
    incident = Incident.query.get_or_404(incident_id)

    if incident.status != "Resolved":
        flash(f"Cannot close — incident must be Resolved first (currently '{incident.status}').", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    incident.status = "Closed"
    incident.closed_at = datetime.utcnow()
    db.session.commit()

    flash(f"Incident '{incident.title}' closed.", "success")
    return redirect(url_for("view_incident", incident_id=incident.id))


# ============================================================
# MILESTONE 3 — Escalation (folded into the Incident system)
#
# There is no separate Alerts page/model any more. The "useful alert
# logic" from that implementation — High/Critical severity meaning an
# incident needs attention, and that attention-need going away once
# Resolved/Closed — is exactly what Incident.is_escalated (defined in
# models.py) already computed automatically. That property is reused
# unchanged and is what drives the warning/escalation badge shown
# directly on the Incident list and detail pages.
#
# This route is the one genuinely new piece of behavior: an explicit,
# admin-performed escalation action that records WHO it was escalated
# to and WHY — real facts that can't be auto-generated the way a
# severity-based flag can.
# ============================================================
@app.route("/incidents/<int:incident_id>/escalate", methods=["POST"])
@login_required
def escalate_incident(incident_id):
    incident = Incident.query.get_or_404(incident_id)

    if incident.status in ("Resolved", "Closed"):
        flash(f"Cannot escalate — incident is already {incident.status}.", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    escalated_to = request.form.get("escalated_to", "").strip()
    escalation_reason = request.form.get("escalation_reason", "").strip()

    if not escalated_to:
        flash("Please specify who this incident is being escalated to.", "error")
        return redirect(url_for("view_incident", incident_id=incident.id))

    incident.escalated = True
    incident.escalated_to = escalated_to
    incident.escalation_reason = escalation_reason or None
    incident.escalated_at = datetime.utcnow()
    db.session.commit()

    flash(f"Incident '{incident.title}' escalated to {escalated_to}.", "success")
    return redirect(url_for("view_incident", incident_id=incident.id))


# ============================================================
# MILESTONE 4, PART 1 — Event Intelligence Engine
#
# This is a MINIMAL, FUNCTIONAL view so the engine can actually be
# run and tested. It is deliberately NOT the polished Executive
# Dashboard — that is explicitly a later Milestone 4 part. This page
# exists only to prove the pipeline works end-to-end on real data.
# ============================================================
@app.route("/intelligence")
@login_required
def intelligence():
    active_alerts, snapshot = intelligence_engine.run_intelligence_cycle(
        db, Attendee, Venue, Session, Sponsor, Incident, IntelligenceAlert, has_session_conflict
    )
    return render_template(
        "intelligence.html",
        alerts=active_alerts,
        total_attendees=snapshot["total_attendees"],
        current_window_registrations=snapshot["current_window_registrations"],
    )


@app.route("/intelligence/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge_intelligence_alert(alert_id):
    alert = IntelligenceAlert.query.get_or_404(alert_id)
    alert.status = "Acknowledged"
    alert.acknowledged_at = datetime.utcnow()
    db.session.commit()
    flash("Alert acknowledged.", "success")
    return redirect(url_for("intelligence"))


# ============================================================
# MILESTONE 4, PART 3 — Agent Orchestration
#
# Trigger: an admin cancels a real session. That single action kicks
# off the full agent workflow. Nothing here duplicates existing logic —
# it calls has_session_conflict() and score_venue() exactly as they
# already exist, and creates real Incident/IntelligenceAlert rows the
# exact same way the manual "Add Incident" and Intelligence Engine
# flows already do.
# ============================================================
@app.route("/sessions/<int:session_id>/cancel", methods=["POST"])
@login_required
def cancel_session(session_id):
    session_obj = Session.query.get_or_404(session_id)

    if session_obj.status == "Cancelled":
        flash("This session is already cancelled.", "error")
        return redirect(url_for("sessions"))

    session_obj.status = "Cancelled"
    db.session.commit()

    run = agent_orchestrator.orchestrate_session_cancellation(
        db, Session, Attendee, Venue, Incident, IntelligenceAlert, OrchestrationRun,
        has_session_conflict, score_venue, session_id=session_id,
    )

    if run.status == "Completed":
        flash(f"Session cancelled. Incident #{run.incident_id} created and the event manager has been alerted.", "success")
    else:
        flash(f"Session marked Cancelled, but the orchestration workflow reported an issue: {run.error_message}", "error")

    return redirect(url_for("orchestration_result", run_id=run.id))


@app.route("/orchestration/<int:run_id>")
@login_required
def orchestration_result(run_id):
    run = OrchestrationRun.query.get_or_404(run_id)
    steps = json.loads(run.steps_json) if run.steps_json else []
    return render_template("orchestration_result.html", run=run, steps=steps)


@app.route("/orchestration/<int:run_id>/approve_notification", methods=["POST"])
@login_required
def approve_orchestration_notification(run_id):
    run = OrchestrationRun.query.get_or_404(run_id)

    if run.notification_status != "Pending Approval":
        flash("This notification has already been actioned.", "error")
        return redirect(url_for("orchestration_result", run_id=run.id))

    session_obj = Session.query.get(run.session_id)
    affected = Attendee.query.filter_by(session_id=run.session_id).all() if session_obj else []

    sent_count = 0
    for attendee in affected:
        try:
            send_cancellation_email(attendee, session_obj)
            sent_count += 1
        except Exception:
            pass  # one bad email address shouldn't block the rest

    run.notification_status = "Sent"
    run.approved_at = datetime.utcnow()
    db.session.commit()

    flash(f"Cancellation notice sent to {sent_count} of {len(affected)} affected attendee(s).", "success")
    return redirect(url_for("orchestration_result", run_id=run.id))


@app.route("/orchestration/<int:run_id>/decline_notification", methods=["POST"])
@login_required
def decline_orchestration_notification(run_id):
    run = OrchestrationRun.query.get_or_404(run_id)
    if run.notification_status == "Pending Approval":
        run.notification_status = "Declined"
        db.session.commit()
        flash("Attendee notification declined — no emails were sent.", "success")
    return redirect(url_for("orchestration_result", run_id=run.id))


with app.app_context():
    db.create_all()

    # ============================================================
    # SELF-HEALING SCHEMA CHECK
    # db.create_all() above only creates tables that don't exist yet —
    # it never adds a new column to a table that already exists. Every
    # "no such column" error in this project so far has been exactly
    # that: a column added to a model in models.py, but never applied
    # to the real, already-existing SQLite table.
    #
    # Running the ALTER TABLE checks here, on every startup, in the
    # SAME process that Flask itself uses to open the database, removes
    # the most common cause of that error: a migration script being run
    # from a different working directory than app.py, which (since
    # "sqlite:///database.db" is a relative path) silently touches a
    # different database.db file than the one Flask actually reads.
    # ============================================================
    from sqlalchemy import text, inspect
    from sqlalchemy.exc import OperationalError

    def _ensure_column(table, column, coltype):
        existing_columns = [c["name"] for c in inspect(db.engine).get_columns(table)]
        if column in existing_columns:
            return
        try:
            with db.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
                conn.commit()
            print(f"[schema check] Added missing column '{table}.{column}'.")
        except OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

    _ensure_column("attendee", "session_id", "INTEGER")
    _ensure_column("attendee", "check_in_time", "DATETIME")
    _ensure_column("attendee", "check_out_time", "DATETIME")
    _ensure_column("venue", "unavailable_reason", "VARCHAR(255)")
    _ensure_column("sponsor", "leads_count",  "INTEGER DEFAULT 0")
    _ensure_column("sponsor", "event_id",     "INTEGER")
    _ensure_column("sponsor", "session_id",   "INTEGER")
    _ensure_column("session", "event_id",     "INTEGER")
    _ensure_column("incident", "investigation_started_at", "DATETIME")
    _ensure_column("incident", "resolved_at",               "DATETIME")
    _ensure_column("incident", "resolution_notes",          "TEXT")
    _ensure_column("incident", "closed_at",                 "DATETIME")
    _ensure_column("incident", "escalated",                 "BOOLEAN DEFAULT 0")
    _ensure_column("incident", "escalated_to",               "VARCHAR(150)")
    _ensure_column("incident", "escalated_at",               "DATETIME")
    _ensure_column("incident", "escalation_reason",          "TEXT")
    _ensure_column("incident", "contact_person",             "VARCHAR(150)")
    _ensure_column("incident", "contact_phone",              "VARCHAR(30)")
    _ensure_column("incident", "alternate_contact",          "VARCHAR(150)")
    _ensure_column("incident", "resolved_by",                "VARCHAR(150)")

    # ------------------------------------------------------------
    # One-time data fix: incidents created under the old 3-stage
    # status vocabulary (Open / In Progress / Resolved) are mapped
    # onto the new 4-stage workflow (Logged / Investigating /
    # Resolved / Closed) so existing incident data keeps working
    # under the new workflow instead of being stuck in a status
    # that no longer exists. Idempotent — after the first run there
    # are no more "Open"/"In Progress" rows left to update.
    # ------------------------------------------------------------
    Incident.query.filter_by(status="Open").update({"status": "Logged"})
    Incident.query.filter_by(status="In Progress").update({"status": "Investigating"})
    db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)