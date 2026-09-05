"""
intelligence_engine.py — Milestone 4, Part 1: Event Intelligence Engine

This is the central intelligence layer described in the Milestone 4 brief.
It is deliberately kept as its own module (unlike the rest of this project,
which lives in one app.py) because it is explicitly meant to become the
central layer that later Agent Orchestration and Executive Dashboard work
will build on — keeping it separate now avoids tangling that future work
into the existing route file.

Pipeline (matches the requested architecture):

    Real event data (existing models)
        -> collect_event_snapshot()      real counts, no mock data
        -> detect_risks(snapshot)        deterministic, rule-based, real thresholds
        -> sync_alerts(risks)            persist as IntelligenceAlert rows, no duplicates
        -> attach_recommendations()      local LLM (Ollama) with rule-based fallback
        -> run_intelligence_cycle()      the one function app.py actually calls

Nothing here replaces or duplicates existing logic — capacity checks reuse
the same real Venue.capacity/Attendee counts already used by registration,
conflict detection reuses has_session_conflict(), sponsor risk reuses
compute_sponsor_performance(), incident risk reads the real Incident table.
"""

from datetime import datetime, timedelta

import requests

# ============================================================
# Configuration
# ============================================================
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
OLLAMA_TIMEOUT_SECONDS = 12  # short on purpose — this must never hang a page load

# Thresholds — deterministic, not something an LLM should decide, since
# these are the safety-critical part the brief explicitly asks to keep rule-based.
VENUE_CAPACITY_WARNING_PCT = 80
VENUE_CAPACITY_CRITICAL_PCT = 100
REGISTRATION_SURGE_WINDOW_MINUTES = 15
REGISTRATION_SURGE_MULTIPLIER = 2.0   # current window vs previous window
CHECKIN_QUEUE_WARNING_COUNT = 10      # registered-but-not-checked-in, for a session starting soon
SESSION_STARTING_SOON_MINUTES = 30
REPEATED_INCIDENT_WINDOW_HOURS = 24
REPEATED_INCIDENT_THRESHOLD = 3       # same category within the window


# ============================================================
# 1. DATA COLLECTION — real data only, from existing models
# ============================================================
def collect_event_snapshot(db, Attendee, Venue, Session, Sponsor, Incident):
    """
    Pulls the real, current state of every module the Intelligence Engine
    needs to reason about. Returns a plain dict — no ORM objects held
    longer than needed, so this is cheap to call on every page load.
    """
    now = datetime.utcnow()

    all_attendees = Attendee.query.all()
    all_sessions = Session.query.all()
    all_venues = Venue.query.all()
    all_incidents = Incident.query.all()

    # --- Registration velocity: real timestamps, two real windows ---
    window_start = now - timedelta(minutes=REGISTRATION_SURGE_WINDOW_MINUTES)
    prev_window_start = now - timedelta(minutes=2 * REGISTRATION_SURGE_WINDOW_MINUTES)
    current_window_count = sum(
        1 for a in all_attendees if a.registration_time and a.registration_time >= window_start
    )
    previous_window_count = sum(
        1 for a in all_attendees
        if a.registration_time and prev_window_start <= a.registration_time < window_start
    )

    # --- Per-session occupancy vs the REAL venue capacity already used
    # by the registration capacity check (same comparison, reused) ---
    session_occupancy = []
    for s in all_sessions:
        if not s.venue:
            continue
        registered_count = sum(1 for a in all_attendees if a.session_id == s.id)
        occupancy_pct = round((registered_count / s.venue.capacity) * 100, 1) if s.venue.capacity else 0
        checked_in_count = sum(
            1 for a in all_attendees if a.session_id == s.id and a.check_in_time and not a.check_out_time
        )
        not_yet_checked_in = sum(
            1 for a in all_attendees if a.session_id == s.id and not a.check_in_time
        )
        starts_at = datetime.combine(s.date, s.start_time) if s.date and s.start_time else None
        minutes_to_start = ((starts_at - now).total_seconds() / 60.0) if starts_at else None

        session_occupancy.append({
            "session": s,
            "registered_count": registered_count,
            "occupancy_pct": occupancy_pct,
            "checked_in_count": checked_in_count,
            "not_yet_checked_in": not_yet_checked_in,
            "minutes_to_start": minutes_to_start,
        })

    # --- Sponsor risk: reuse the real, already-tested performance calc ---
    # Imported lazily to avoid a circular import (app.py imports this module).
    from app import compute_sponsor_performance
    sponsor_perf, _ = compute_sponsor_performance()

    # --- Incidents: real severity/status/category data ---
    active_incidents = [i for i in all_incidents if i.status not in ("Resolved", "Closed")]
    high_severity_active = [i for i in active_incidents if i.severity in ("High", "Critical")]

    return {
        "now": now,
        "total_attendees": len(all_attendees),
        "current_window_registrations": current_window_count,
        "previous_window_registrations": previous_window_count,
        "session_occupancy": session_occupancy,
        "all_sessions": all_sessions,
        "sponsor_performance": sponsor_perf,
        "all_incidents": all_incidents,
        "active_incidents": active_incidents,
        "high_severity_active": high_severity_active,
    }


# ============================================================
# 2. RISK DETECTION — deterministic, real thresholds
# ============================================================
def detect_risks(snapshot, has_session_conflict_fn):
    """
    Returns a list of plain dicts describing detected risks. Every field
    comes from real data in the snapshot — nothing here is invented.
    """
    risks = []
    now = snapshot["now"]

    # --- Venue/session capacity risk ---
    for occ in snapshot["session_occupancy"]:
        s = occ["session"]
        if occ["occupancy_pct"] >= VENUE_CAPACITY_CRITICAL_PCT:
            risks.append({
                "alert_type": "Venue Capacity",
                "severity": "Critical",
                "message": f"'{s.title}' has reached {occ['occupancy_pct']}% of {s.venue.name}'s capacity ({occ['registered_count']}/{s.venue.capacity}).",
                "source_module": "Venue",
                "session_id": s.id,
                "venue_id": s.venue_id,
            })
        elif occ["occupancy_pct"] >= VENUE_CAPACITY_WARNING_PCT:
            risks.append({
                "alert_type": "Venue Capacity",
                "severity": "Warning",
                "message": f"'{s.title}' is approaching capacity at {s.venue.name} — {occ['occupancy_pct']}% full ({occ['registered_count']}/{s.venue.capacity}).",
                "source_module": "Venue",
                "session_id": s.id,
                "venue_id": s.venue_id,
            })

        # --- Check-in queue risk: session starting soon, many not checked in ---
        if (occ["minutes_to_start"] is not None
                and 0 <= occ["minutes_to_start"] <= SESSION_STARTING_SOON_MINUTES
                and occ["not_yet_checked_in"] >= CHECKIN_QUEUE_WARNING_COUNT):
            risks.append({
                "alert_type": "Check-in Queue",
                "severity": "Warning",
                "message": f"'{s.title}' starts in {int(occ['minutes_to_start'])} min with {occ['not_yet_checked_in']} attendees not yet checked in.",
                "source_module": "Check-in",
                "session_id": s.id,
                "venue_id": s.venue_id,
            })

    # --- Registration surge risk ---
    prev = snapshot["previous_window_registrations"]
    curr = snapshot["current_window_registrations"]
    if prev > 0 and curr >= prev * REGISTRATION_SURGE_MULTIPLIER and curr >= 5:
        risks.append({
            "alert_type": "Registration Surge",
            "severity": "Warning",
            "message": f"Registrations in the last {REGISTRATION_SURGE_WINDOW_MINUTES} minutes ({curr}) are more than {REGISTRATION_SURGE_MULTIPLIER}x the previous window ({prev}).",
            "source_module": "Registration",
        })

    # --- Session/speaker/venue scheduling conflicts (reuses existing function) ---
    seen_conflicts = set()
    for s in snapshot["all_sessions"]:
        if not (s.venue_id or s.speaker_id):
            continue
        conflict_msg = has_session_conflict_fn(
            s.date, s.start_time, s.end_time,
            venue_id=s.venue_id, speaker_id=s.speaker_id, exclude_session_id=s.id,
        )
        if conflict_msg and s.id not in seen_conflicts:
            seen_conflicts.add(s.id)
            risks.append({
                "alert_type": "Session Conflict",
                "severity": "Critical",
                "message": f"'{s.title}': {conflict_msg}",
                "source_module": "Session",
                "session_id": s.id,
                "venue_id": s.venue_id,
            })

    # --- High-severity active incidents ---
    for inc in snapshot["high_severity_active"]:
        risks.append({
            "alert_type": "High-Severity Incident",
            "severity": "Critical" if inc.severity == "Critical" else "Warning",
            "message": f"'{inc.title}' is {inc.severity} severity and still {inc.status}.",
            "source_module": "Incident",
            "incident_id": inc.id,
        })

    # --- Repeated incidents in the same category ---
    window_start = now - timedelta(hours=REPEATED_INCIDENT_WINDOW_HOURS)
    recent = [i for i in snapshot["all_incidents"] if i.reported_time and i.reported_time >= window_start]
    by_category = {}
    for i in recent:
        if not i.category:
            continue
        by_category.setdefault(i.category, []).append(i)
    for category, incs in by_category.items():
        if len(incs) >= REPEATED_INCIDENT_THRESHOLD:
            latest = max(incs, key=lambda i: i.reported_time)
            risks.append({
                "alert_type": "Repeated Incidents",
                "severity": "Warning",
                "message": f"{len(incs)} '{category}' incidents reported in the last {REPEATED_INCIDENT_WINDOW_HOURS} hours — this may be a pattern, not isolated events.",
                "source_module": "Incident",
                "incident_id": latest.id,
            })

    # --- Sponsor performance/deliverable risk (reuses real scored data) ---
    for item in snapshot["sponsor_performance"]:
        if item["perf_status"] == "At Risk":
            sponsor = item["sponsor"]
            risks.append({
                "alert_type": "Sponsor Risk",
                "severity": "Warning",
                "message": f"Sponsor '{sponsor.company_name}' is At Risk (score {item['overall_score']}/100) — check payment progress and deliverables.",
                "source_module": "Sponsor",
                "sponsor_id": sponsor.id,
            })

    return risks


# ============================================================
# 3. ALERT PERSISTENCE — idempotent, never duplicates
# ============================================================
def sync_alerts(db, IntelligenceAlert, risks):
    """
    Ensures each currently-detected risk has exactly one tracked
    IntelligenceAlert row (status Active OR Acknowledged — both count
    as "still being tracked", so acknowledging an alert for an ongoing
    risk does not cause a duplicate to be created on the next cycle).
    Matching key: alert_type + whichever real reference (session/venue/
    incident/sponsor) applies. Risks that are no longer detected have
    their matching tracked alerts marked Resolved automatically.
    """
    ref_fields = ["session_id", "venue_id", "incident_id", "sponsor_id", "event_id"]

    def ref_key(d):
        return tuple(d.get(f) for f in ref_fields)

    tracked_alerts = IntelligenceAlert.query.filter(IntelligenceAlert.status.in_(["Active", "Acknowledged"])).all()
    existing_by_key = {(a.alert_type, ref_key({f: getattr(a, f) for f in ref_fields})): a for a in tracked_alerts}

    current_keys = set()
    for risk in risks:
        key = (risk["alert_type"], ref_key(risk))
        current_keys.add(key)
        existing = existing_by_key.get(key)
        if existing:
            # Same situation still ongoing — refresh the message/severity
            # in case the numbers changed, but don't create a new row,
            # and don't touch its Active/Acknowledged status either way.
            existing.message = risk["message"]
            existing.severity = risk["severity"]
        else:
            db.session.add(IntelligenceAlert(
                alert_type=risk["alert_type"],
                severity=risk["severity"],
                message=risk["message"],
                source_module=risk["source_module"],
                session_id=risk.get("session_id"),
                venue_id=risk.get("venue_id"),
                incident_id=risk.get("incident_id"),
                sponsor_id=risk.get("sponsor_id"),
                event_id=risk.get("event_id"),
                detected_at=datetime.utcnow(),
                status="Active",
            ))

    # Anything that was tracked but is no longer being detected has resolved itself.
    for key, alert in existing_by_key.items():
        if key not in current_keys:
            alert.status = "Resolved"

    db.session.commit()
    return IntelligenceAlert.query.filter_by(status="Active").order_by(IntelligenceAlert.detected_at.desc()).all()


# ============================================================
# 4. RECOMMENDATION LAYER — local LLM with rule-based fallback
# ============================================================
_RULE_BASED_FALLBACKS = {
    "Venue Capacity": "Consider opening an alternate entry point or deploying additional staff to manage flow at this venue.",
    "Check-in Queue": "Deploy additional check-in staff now — the session is starting soon and the queue has not cleared.",
    "Registration Surge": "Monitor closely; if this continues, ensure enough on-site staff are available to handle the increased load.",
    "Session Conflict": "Reassign the conflicting venue or speaker before the session date to avoid a double-booking on the day.",
    "High-Severity Incident": "Ensure this incident is being actively investigated and escalate if it is not resolved shortly.",
    "Repeated Incidents": "Investigate whether these incidents share a common root cause rather than treating each one in isolation.",
    "Sponsor Risk": "Follow up directly with the sponsor on outstanding payment and pending deliverables.",
}


def _call_local_llm(prompt):
    """
    Calls a local Ollama instance. Returns the generated text, or None if
    Ollama is not reachable/times out/errors — callers must treat None as
    "fall back to rule-based text", never as an error to surface to the user.
    This has NOT been tested against a live Ollama instance from this
    environment (no network access to a user's local machine) — it is
    built to the documented Ollama HTTP API and fails safely if wrong.
    """
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            text = response.json().get("response", "").strip()
            return text or None
    except requests.exceptions.RequestException:
        pass
    return None


def generate_recommendation(risk_dict):
    """
    Contextual, natural-language recommendation for one detected risk.
    Tries the local LLM first (grounded only in this risk's real message/
    type/severity — never told to invent facts), falls back to a fixed,
    still-real rule-based line if the LLM is unavailable.
    """
    prompt = (
        "You are an event operations assistant. A monitoring system just detected the "
        "following real situation at a live event. In 1-2 short sentences, recommend a "
        "practical, immediate action. Do not restate the situation, just give the action.\n\n"
        f"Alert type: {risk_dict['alert_type']}\n"
        f"Severity: {risk_dict['severity']}\n"
        f"Situation: {risk_dict['message']}\n"
    )
    llm_result = _call_local_llm(prompt)
    if llm_result:
        return llm_result
    return _RULE_BASED_FALLBACKS.get(risk_dict["alert_type"], "Review this situation and take appropriate action.")


# ============================================================
# 5. ORCHESTRATION — the one function app.py calls
# ============================================================
def run_intelligence_cycle(db, Attendee, Venue, Session, Sponsor, Incident, IntelligenceAlert, has_session_conflict_fn):
    """
    Full pipeline: collect -> detect -> persist -> recommend.
    Returns the current list of Active alerts (with .recommendation set).
    """
    snapshot = collect_event_snapshot(db, Attendee, Venue, Session, Sponsor, Incident)
    risks = detect_risks(snapshot, has_session_conflict_fn)
    active_alerts = sync_alerts(db, IntelligenceAlert, risks)

    # Only generate a recommendation for alerts that don't already have one —
    # avoids re-calling the LLM on every page load for an unchanged alert.
    for alert in active_alerts:
        if not alert.recommendation:
            risk_dict = {"alert_type": alert.alert_type, "severity": alert.severity, "message": alert.message}
            alert.recommendation = generate_recommendation(risk_dict)
    db.session.commit()

    return active_alerts, snapshot