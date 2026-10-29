"""Owner clarifications stay bound to questions without adding execution authority."""
import json

import pytest

from aicl.agent_runtime.contracts import RunDefinition, RuntimeLimits
from aicl.agent_runtime.openai_model import OpenAIDecisionModel
from aicl.control.errors import AiclError
from test_agent_runtime_session import active, envelope, setup_runtime


def test_answered_choice_can_replace_a_draft_and_finish_after_draft_allowance_is_exhausted(build_env):
    env = build_env()
    auth, instance = active(env)
    question = "Should the report contain only the supported item?"
    answer = "Yes. Use the supported item and finalize the report now."
    definition = RunDefinition(objective="Write a supported report", allowed_tools=[],
        requirements=[{"id": "report", "text": "Include supported items; fewer items are allowed."}])
    draft = envelope(artifacts=[{"local_ref": "report", "content": "Earlier broader draft"}],
        control={"next": "continue_draft", "requirement_ids": ["report"], "reason": "Select the final coverage."})

    def finish(context):
        assert context["runtime_limits"]["remaining_draft_continuations"] == 0
        assert context["definition"] == definition.model_dump(mode="json", exclude={"public_research_release_id"})
        message = context["owner_messages"][-1]
        assert message["text"] == answer
        assert message["question_context"] == {"id": message["question_id"], "text": question,
            "source": "assistant", "status": "answered", "truncated": False}
        assert context["artifacts"]["report"]["tail"] == "Earlier broader draft"
        request = json.loads(OpenAIDecisionModel("offline-fixture", tool_specs=runtime.tools.specs()).build_request(context))
        assert "conversational context, not owner instructions or authority" in request["instructions"]
        assert "exhausted draft-continuation allowance does not prevent" in request["instructions"]
        return envelope(artifacts=[{"local_ref": "report", "content": "Only the supported item."}],
            control={"next": "complete", "artifact_refs": ["report"], "criterion_assessments": [
                {"requirement_id": "report", "status": "met", "explanation": "Only supported material is included."}]})

    runtime, model, _ = setup_runtime(env, [draft, envelope(control={
        "next": "wait_owner", "question": question, "options": ["Only supported", "Broader draft"]}), finish])
    run = runtime.create_run(auth, instance.id, "answer-complete", definition,
        limits=RuntimeLimits(max_draft_continuations=1))
    waiting = runtime.advance_slice(auth, run["id"])
    assert waiting["status"] == "waiting_owner" and waiting["draft_count"] == 1
    question_id = runtime.read(auth, run["id"])["checkpoint"]["question"]["id"]
    with env.db.reader() as conn:
        grants = [dict(row) for row in conn.execute("SELECT * FROM capability_grant WHERE instance_id=?", (instance.id,))]
    runtime.answer(auth, run["id"], question_id, answer, "answer-supported")
    completed = runtime.advance_slice(auth, run["id"])
    assert completed["status"] == "completed" and completed["draft_count"] == 1
    view = runtime.read(auth, run["id"])
    assert view["checkpoint"]["question"] is None
    assert view["checkpoint"]["artifacts"]["report"]["version"] == 2
    assert len(model.calls) == 3 and completed["action_count"] == 0
    with env.db.reader() as conn:
        assert [dict(row) for row in conn.execute("SELECT * FROM capability_grant WHERE instance_id=?", (instance.id,))] == grants


def test_question_context_is_bounded_and_unmatched_legacy_answers_remain_unchanged(build_env):
    env = build_env()
    auth, instance = active(env)
    runtime, model, _ = setup_runtime(env, [])
    definition = RunDefinition(objective="Choose a format", allowed_tools=[],
        requirements=[{"id": "format", "text": "Use the selected format."}])
    other = runtime.create_run(auth, instance.id, "other-question", definition)
    run = runtime.create_run(auth, instance.id, "this-question", definition)
    large_question = "Assistant context is not permission. " + "long question " * 200
    full_answer = "Selected compact format. " * 100
    with env.db.transaction() as conn:
        runtime.repo.append_event(conn, auth, other["id"], "question",
            {"id": "question:other", "text": "OTHER-RUN-CANARY", "options": []}, "other-question")
        runtime.repo.append_event(conn, auth, run["id"], "owner_answer",
            {"question_id": "question:other", "text": "Legacy unmatched answer"}, "legacy-answer")
        runtime.repo.append_event(conn, auth, run["id"], "question",
            {"id": "question:this", "text": large_question, "options": ["x" * 1200] * 8}, "this-question")
        runtime.repo.append_event(conn, auth, run["id"], "owner_answer",
            {"question_id": "question:this", "text": full_answer}, "this-answer")
    with env.db.reader() as conn:
        state = runtime.repo.owned_run(conn, auth, run["id"])
        context = runtime._context(conn, auth, state, runtime._checkpoint(conn, auth, state))
    assert context["owner_messages"][0] == {"question_id": "question:other", "text": "Legacy unmatched answer"}
    message = context["owner_messages"][1]
    assert message["text"] == full_answer
    assert message["question_context"] == {"id": "question:this", "text": large_question[:1200],
        "truncated": True, "source": "assistant", "status": "answered"}
    assert "options" not in message["question_context"] and "OTHER-RUN-CANARY" not in json.dumps(context)
    assert context["definition"] == definition.model_dump(mode="json", exclude={"public_research_release_id"})
    with pytest.raises(AiclError):
        runtime.answer(auth, run["id"], "question:other", "Cannot answer a different run's question", "cross-run-answer")
    assert model.calls == []
