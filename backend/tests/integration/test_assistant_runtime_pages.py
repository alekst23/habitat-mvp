"""The existing chat presents scoped work without treating generated text as UI."""

from aicl.chat.assistant_pages import render_assistant


RUN_ID = "f1791215-2781-4142-a219-4d6f967d15e5"
INSTANCE_ID = "867789f9-397f-496a-9b11-90767cfbb1fd"


def page(**changes):
    return render_assistant(messages=[], session_id="session", proposal=None,
                            csrf="csrf", request_id="request", usage={}, **changes)


def test_runtime_start_requires_explicit_web_read_selection_and_preserves_setup():
    html = page(runtime_available=True, runtime_candidates=[{
        "id": INSTANCE_ID, "name": "Library <planner>",
        "tools": [{"name": "web.read", "title": "Read public web pages"}],
        "setup_href": f"/instances/{INSTANCE_ID}",
    }])
    assert 'action="/chat/runs/start"' in html
    assert f'<option value="{INSTANCE_ID}" selected ' in html
    assert "Library &lt;planner&gt;" in html
    assert 'name="tools" value="web.read"' in html
    assert 'name="tools" value="web.read" checked' not in html
    assert "Search and browser interaction are unavailable" in html
    assert 'action="/chat/messages"' in html and "A plan takes shape here" in html
    assert 'action="/chat/runs/start"' not in page()


def test_linked_run_escapes_content_targets_answers_and_shows_current_controls():
    run = {"id": RUN_ID, "status": "waiting_owner", "version": 7,
           "reason": None, "objective": "Prepare a library plan",
           "plan": [{"id": "research", "title": "Read <sources>", "state": "completed", "summary": "Evidence saved"}],
           "artifacts": [{"name": "Draft", "version": 2, "content": '<script>alert("x")</script>', "completed": False}],
           "question": {"id": "question-1", "text": "Which audience?", "options": ["Adults", "Children"]},
           "can_pause": True, "can_resume": False, "can_cancel": True, "can_advance": False}
    html = page(runtime_available=True, runtime_run=run)
    assert "Needs your input" in html and "Read &lt;sources&gt;" in html
    assert "&lt;script&gt;alert" in html and '<script>alert("x")</script>' not in html
    assert 'name="run_id" value="' + RUN_ID + '"' in html
    assert 'name="question_id" value="question-1"' in html
    assert "Answer the agent’s question" in html and "Which audience?" in html
    assert 'data-assistant-option="Adults"' in html
    assert f'action="/chat/runs/{RUN_ID}/pause"' in html
    assert f'action="/chat/runs/{RUN_ID}/cancel"' in html
    assert f'action="/chat/runs/{RUN_ID}/resume"' not in html
    assert "A plan takes shape here" not in html
    completed = page(runtime_available=True, runtime_run={**run, "status": "completed", "question": None,
                                                       "can_pause": False, "can_cancel": False})
    assert "This work is complete" in completed
    assert 'data-assistant-submit="message" hidden' in completed
    assert f'action="/chat/runs/{RUN_ID}/pause"' not in completed


def test_saved_runtime_messages_retain_event_identity_and_escape_text():
    html = render_assistant(messages=[{"id": RUN_ID, "role": "assistant", "text": "Read <sources>"},
                                      {"role": "user", "text": "Prior setup message"}],
                            session_id="session", proposal=None, csrf="csrf", request_id="request", usage={})
    assert f'data-runtime-event-id="{RUN_ID}"' in html
    assert html.count("data-runtime-event-id=") == 1
    assert "Read &lt;sources&gt;" in html and "Read <sources>" not in html


def test_unfunded_agent_and_blocked_run_offer_checkout_before_execution():
    readiness = {"ready": False, "balance_micro_usd": 0, "required_micro_usd": 165000,
                 "blockers": [{"reason": "credit_insufficient", "message": "Add service credit before starting work."},
                              {"reason": "budget_exhausted", "message": "Review spending limits."}]}
    candidate = {"id": INSTANCE_ID, "name": "Report agent", "tools": [], "readiness": readiness}
    html = page(runtime_available=True, runtime_candidates=[candidate])
    assert 'action="/chat/funding"' in html
    assert "Add funds with PayPal" in html
    assert "$0.165" in html and "$0.00" in html
    assert f'href="/instances/{INSTANCE_ID}#budgets"' in html
    assert 'data-start-work disabled' in html
    run = {"id": RUN_ID, "instance_id": INSTANCE_ID, "status": "blocked", "version": 2,
           "reason": "credit_insufficient", "objective": "Write report", "plan": [], "artifacts": [],
           "question": None, "can_pause": True, "can_resume": False, "can_cancel": True, "can_advance": False,
           "readiness": readiness}
    blocked = page(runtime_available=True, runtime_run=run)
    assert 'action="/chat/funding"' in blocked and "Add funds with PayPal" in blocked
    assert "credit insufficient" not in blocked
    assert f'action="/chat/runs/{RUN_ID}/resume"' not in blocked
