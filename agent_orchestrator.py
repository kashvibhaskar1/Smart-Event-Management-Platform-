"""
agent_orchestrator.py — Milestone 4, Part 3: Agent Orchestration

Demonstrates the required workflow:

    Speaker Agent detects cancellation
        -> Intelligence Engine analyzes impact
        -> Venue Agent checks alternative rooms/times
        -> Registration/Attendee system identifies affected attendees
        -> Incident Agent creates incident
        -> Operational Alert notifies event manager
        -> Executive Dashboard reflects updated status

Every step below calls a REAL, already-existing piece of this project
rather than reimplementing it:
  - Venue scoring reuses score_venue() from app.py, unchanged.
  - Incident creation follows the exact same pattern add_incident() uses
    (always starts "Logged" — the orchestrator does not bypass that rule).
  - Escalation sets the exact same fields the manual /escalate route sets.
  - The alert's recommendation reuses intelligence_engine.generate_recommendation(),
    the same function already backing /intelligence and the Dashboard.
  - The Executive Dashboard needs NO new code at all — it already
    re-queries Incident/IntelligenceAlert live on every load, so it
    reflects this workflow's output automatically the moment it commits.

The one thing this orchestrator deliberately does NOT do automatically
is send real emails to real people (affected attendees, the displaced
speaker) — that is gated behind explicit human approval, recorded on
the OrchestrationRun itself, and only sent when an admin takes a
separate, explicit action.
"""

import json
import time
from datetime import datetime

import intelligence_engine


# ============================================================
# STEP 1 — Speaker / Session Agent: confirms the real cancellation
# ============================================================
def speaker_agent_detect_cancellation(session):
    return {
        "session_id": session.id,
        "title": session.title,
        "speaker_name": session.speaker.name if session.speaker else None,
        "speaker_email": session.speaker.email if session.speaker else None,
        "venue_name": session.venue.name if session.venue else None,
        "venue_capacity": session.venue.capacity if session.venue else None,
        "date": session.date,
        "start_time": session.start_time,
        "end_time": session.end_time,
        "is_cancelled": session.status == "Cancelled",
    }


# ============================================================
# STEP 2 — Intelligence Engine: sizes the real impact
# ============================================================
def intelligence_engine_analyze_impact(session, Attendee):
    affected_count = Attendee.query.filter_by(session_id=session.id).count()
    already_checked_in = Attendee.query.filter(
        Attendee.session_id == session.id, Attendee.check_in_time.isnot(None)
    ).count()

    if affected_count >= 30:
        severity = "Critical"
    elif affected_count >= 10:
        severity = "High"
    elif affected_count > 0:
        severity = "Medium"
    else:
        severity = "Low"

    return {
        "affected_attendee_count": affected_count,
        "already_checked_in_count": already_checked_in,
        "impact_severity": severity,
    }


# ============================================================
# STEP 3 — Venue Agent: reuses score_venue() (from app.py) to rank
# real, currently-free venues with enough capacity
# ============================================================
def venue_agent_find_alternatives(session, affected_count, Venue, has_session_conflict_fn, score_venue_fn, limit=3):
    candidates = []
    min_capacity = max(affected_count, 1)

    for v in Venue.query.filter(Venue.capacity >= min_capacity, Venue.availability == True).all():  # noqa: E712
        if v.id == session.venue_id:
            continue
        conflict = has_session_conflict_fn(
            session.date, session.start_time, session.end_time,
            venue_id=v.id, exclude_session_id=session.id,
        )
        if conflict:
            continue
        scored = score_venue_fn(
            venue=v, attendees=affected_count, location=None,
            event_type=None, facilities_required=[], budget=None,
        )
        candidates.append(scored)

    candidates.sort(key=lambda c: -c["score"])
    return candidates[:limit]


# ============================================================
# STEP 4 — Registration / Attendee Agent: real affected attendees
# ============================================================
def registration_agent_identify_affected(session, Attendee):
    return Attendee.query.filter_by(session_id=session.id).all()


# ============================================================
# STEP 5 — Incident Agent: creates a real Incident, exactly the way
# add_incident() already does (always starts "Logged")
# ============================================================
def incident_agent_create_incident(db, Incident, session_facts, impact, alternatives):
    alt_text = (
        f"{len(alternatives)} alternative venue(s) identified: "
        + ", ".join(f"{c['venue'].name} (score {c['score']}/100)" for c in alternatives)
        if alternatives else "No suitable alternative venue was found."
    )
    description = (
        f"Session '{session_facts['title']}' was cancelled"
        + (f", speaker {session_facts['speaker_name']}" if session_facts['speaker_name'] else "")
        + f". {impact['affected_attendee_count']} attendee(s) were registered"
        + (f" ({impact['already_checked_in_count']} already checked in)" if impact['already_checked_in_count'] else "")
        + f". {alt_text}"
    )

    incident = Incident(
        title=f"Session Cancelled: {session_facts['title']}",
        description=description,
        category="Logistics",
        location=session_facts.get("venue_name") or "Not specified",
        severity=impact["impact_severity"] if impact["impact_severity"] != "Low" else "Medium",
        status="Logged",
        assigned_to="Event Operations Manager",
        reported_time=datetime.utcnow(),
    )
    db.session.add(incident)
    db.session.flush()  # get incident.id without a full commit yet
    return incident


# ============================================================
# ESCALATION — reuses the exact same fields the manual /escalate
# route already sets, just triggered by the orchestrator itself
# ============================================================
def maybe_escalate(incident, impact, alternatives):
    should_escalate = impact["impact_severity"] in ("Critical", "High") or not alternatives
    if not should_escalate:
        return False, None

    reasons = []
    if impact["impact_severity"] in ("Critical", "High"):
        reasons.append(f"{impact['affected_attendee_count']} attendees affected")
    if not alternatives:
        reasons.append("no alternative venue available")
    reason = "Auto-escalated by Agent Orchestrator: " + ", ".join(reasons) + "."

    incident.escalated = True
    incident.escalated_to = "Event Operations Manager"
    incident.escalation_reason = reason
    incident.escalated_at = datetime.utcnow()
    return True, reason


# ============================================================
# STEP 6 — Operational Alert: reuses the real IntelligenceAlert model
# and the SAME recommendation function already backing /intelligence
# and the Dashboard. Includes a genuine retry, not just a fallback.
# ============================================================
def operational_alert_notify(db, IntelligenceAlert, session_facts, incident, impact):
    message = (
        f"Session '{session_facts['title']}' cancelled — "
        f"{impact['affected_attendee_count']} attendee(s) affected. See Incident #{incident.id}."
    )
    risk_dict = {
        "alert_type": "Session Cancellation",
        "severity": "Critical" if impact["impact_severity"] == "Critical" else "Warning",
        "message": message,
    }

    recommendation = None
    last_error = None
    for attempt in range(2):  # genuine retry: up to 2 attempts before giving up
        try:
            recommendation = intelligence_engine.generate_recommendation(risk_dict)
            break
        except Exception as e:  # generate_recommendation already catches its own
            last_error = e       # request errors internally, so this only catches
            time.sleep(0.5)       # something unexpected — still worth retrying once.
    if not recommendation:
        recommendation = "Reassign affected attendees and notify the speaker as soon as possible."

    alert = IntelligenceAlert(
        alert_type=risk_dict["alert_type"],
        severity=risk_dict["severity"],
        message=message,
        source_module="Session",
        recommendation=recommendation,
        session_id=session_facts["session_id"],
        incident_id=incident.id,
        detected_at=datetime.utcnow(),
        status="Active",
    )
    db.session.add(alert)
    db.session.flush()
    return alert


# ============================================================
# ORCHESTRATOR — ties every step together, manages sequencing,
# context passing, error handling, and the human-approval gate.
# ============================================================
def orchestrate_session_cancellation(db, Session, Attendee, Venue, Incident, IntelligenceAlert,
                                      OrchestrationRun, has_session_conflict_fn, score_venue_fn,
                                      session_id):
    steps = []

    def log_step(agent, status, summary):
        steps.append({"agent": agent, "status": status, "summary": summary})

    session_obj = Session.query.get(session_id)
    if not session_obj:
        run = OrchestrationRun(
            workflow_name="Session Cancellation", session_id=session_id,
            steps_json=json.dumps([{"agent": "Orchestrator", "status": "failed", "summary": "Session not found."}]),
            status="Failed", error_message="Session not found.",
        )
        db.session.add(run)
        db.session.commit()
        return run

    try:
        # --- Step 1: Speaker/Session Agent ---
        session_facts = speaker_agent_detect_cancellation(session_obj)
        log_step("Speaker/Session Agent", "ok",
                  f"Confirmed cancellation of '{session_facts['title']}'"
                  + (f" (speaker: {session_facts['speaker_name']})" if session_facts["speaker_name"] else ""))

        if not session_facts["is_cancelled"]:
            log_step("Orchestrator", "aborted", "Session status is not 'Cancelled' — nothing to do.")
            run = OrchestrationRun(
                workflow_name="Session Cancellation", session_id=session_id,
                steps_json=json.dumps(steps), status="Failed",
                error_message="Session is not marked Cancelled.",
            )
            db.session.add(run)
            db.session.commit()
            return run

        # --- Step 2: Intelligence Engine impact analysis ---
        impact = intelligence_engine_analyze_impact(session_obj, Attendee)
        log_step("Intelligence Engine", "ok",
                  f"Impact: {impact['affected_attendee_count']} attendee(s) affected "
                  f"({impact['impact_severity']} severity), {impact['already_checked_in_count']} already checked in.")

        # --- Step 3: Venue Agent (non-critical-path: failure here
        # should not abort the whole workflow) ---
        try:
            alternatives = venue_agent_find_alternatives(
                session_obj, impact["affected_attendee_count"], Venue, has_session_conflict_fn, score_venue_fn
            )
            log_step("Venue Agent", "ok",
                      f"Found {len(alternatives)} alternative venue(s)." if alternatives
                      else "No suitable alternative venue found.")
        except Exception as e:
            alternatives = []
            log_step("Venue Agent", "error", f"Could not search for alternatives: {e}")

        # --- Step 4: Registration/Attendee Agent ---
        affected_attendees = registration_agent_identify_affected(session_obj, Attendee)
        log_step("Registration/Attendee Agent", "ok",
                  f"Identified {len(affected_attendees)} affected attendee(s) by real registration records.")

        # --- Step 5: Incident Agent (critical path — failure here
        # means the whole run failed, since the incident is the core
        # deliverable of this workflow) ---
        incident = incident_agent_create_incident(db, Incident, session_facts, impact, alternatives)
        log_step("Incident Agent", "ok", f"Created Incident #{incident.id}: '{incident.title}' (status: Logged).")

        # --- Escalation ---
        escalated, escalation_reason = maybe_escalate(incident, impact, alternatives)
        if escalated:
            log_step("Orchestrator", "ok", f"Auto-escalated Incident #{incident.id}: {escalation_reason}")

        # --- Step 6: Operational Alert ---
        alert = operational_alert_notify(db, IntelligenceAlert, session_facts, incident, impact)
        log_step("Operational Alert", "ok", f"Alert #{alert.id} created for the event manager, with a recommendation.")

        # --- Step 7: Executive Dashboard — no code needed here. It
        # already queries Incident/IntelligenceAlert live, so it will
        # reflect this the moment the transaction below commits. ---
        log_step("Executive Dashboard", "ok",
                  "No action needed — the Dashboard reads Incident/IntelligenceAlert live and will "
                  "reflect this the moment this run commits.")

        run = OrchestrationRun(
            workflow_name="Session Cancellation",
            session_id=session_id,
            incident_id=incident.id,
            alert_id=alert.id,
            steps_json=json.dumps(steps, default=str),
            affected_attendee_count=impact["affected_attendee_count"],
            alternative_venue_count=len(alternatives),
            escalated=escalated,
            escalation_reason=escalation_reason,
            notification_status="Pending Approval",
            status="Completed",
        )
        db.session.add(run)
        db.session.commit()
        return run

    except Exception as e:
        db.session.rollback()
        log_step("Orchestrator", "error", f"Workflow failed: {e}")
        run = OrchestrationRun(
            workflow_name="Session Cancellation", session_id=session_id,
            steps_json=json.dumps(steps, default=str), status="Failed", error_message=str(e),
        )
        db.session.add(run)
        db.session.commit()
        return run