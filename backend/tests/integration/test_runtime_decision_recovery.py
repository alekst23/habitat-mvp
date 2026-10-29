"""Invalid provider decisions recover within the existing AICL retry allowance."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import httpx
import pytest

from aicl.agent_runtime.contracts import DecisionEnvelope
from aicl.agent_runtime.coordinator import AgentRuntime
from aicl.agent_runtime.openai_model import MODEL, OpenAIDecisionModel
from test_agent_runtime_session import active, definition, envelope, finish, setup_runtime
from test_runtime_agent_research import agent_setup
from test_runtime_research_prelude import rows


@pytest.mark.parametrize('recover', [True, False])
def test_invalid_provider_decision_keeps_research_and_retries_without_effects_or_free_usage(build_env, recover):
    env, auth, _, runtime, _, _, run, outbound, dns, planner = agent_setup(
        lambda: build_env(start=datetime(2026, 10, 28, tzinfo=timezone.utc)))
    calls = []
    allow_correction = [recover]
    untrusted_marker = 'UNTRUSTED-OUTPUT-DO-NOT-REFLECT'

    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body['input'][0]['content'])
        calls.append(deepcopy(context))
        assert body['tools'] == []
        assert [tool['name'] for tool in context['available_tools']] == ['artifact.read']
        evidence_ref = context['public_research']['evidence_ref']
        if len(calls) == 1 or not allow_correction[0]:
            # A malformed local plan reference must reject the entire decision,
            # including its otherwise valid action and draft artifact.
            decision = DecisionEnvelope.model_validate({
                'schema_version': 1,
                'output': {'artifacts': [{'local_ref': 'rejected', 'content': untrusted_marker}]},
                'actions': [{'name': 'artifact.read', 'arguments': {'ref': evidence_ref}, 'plan_item_id': None}],
                'control': {'next': 'continue'},
            }).model_dump(mode='json')
            decision['actions'][0]['plan_item_id'] = untrusted_marker + ' contains spaces'
            decision['actions'][0]['arguments'].update(offset=None, max_chars=None, source_index=None, public_preview=None, field=None)
        else:
            decision = DecisionEnvelope.model_validate({
                'schema_version': 1,
                'output': {'artifacts': [{'local_ref': 'report', 'content': 'Public evidence is saved at https://news.example/article.',
                                          'evidence_refs': [evidence_ref]}]},
                'control': {'next': 'complete', 'artifact_refs': ['report'], 'criterion_assessments': [
                    {'requirement_id': 'report', 'status': 'met', 'explanation': 'The report cites the saved public evidence.',
                     'evidence_refs': [evidence_ref]}]},
            }).model_dump(mode='json')
        return httpx.Response(200, json={
            'id': f'resp_recovery_{len(calls)}', 'object': 'response', 'model': MODEL,
            'service_tier': 'default', 'status': 'completed',
            'usage': {'input_tokens': 500, 'output_tokens': 100, 'total_tokens': 600},
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps({'decision': decision})}]}],
        })

    runtime.model = OpenAIDecisionModel('offline-recovery-fixture', tool_specs=runtime.tools.specs(),
                                      transport=httpx.MockTransport(respond))
    result = runtime.advance_slice(auth, run['id'])
    assert len(calls) == 2
    assert result['status'] == ('completed' if recover else 'blocked')
    assert result['invalid_count'] == (1 if recover else 2)
    # The public phase consumes its reserved seven-action bound exactly once.
    assert result['decision_count'] == 2 and result['action_count'] == 7
    assert set(result['checkpoint']['artifacts']) == ({'report'} if recover else set())
    assert not result['checkpoint']['memory'] and not result['checkpoint']['plan']
    assert len(planner.calls) == 3 and len(outbound) == 2
    assert dns == ['api.search.brave.com', 'news.example']
    assert calls[0]['public_research'] == calls[1]['public_research'] == result['public_research']
    assert calls[0]['public_research']['successful_searches'] == 1
    assert calls[0]['public_research']['successful_page_reads'] == 1
    assert all(untrusted_marker not in json.dumps(call) for call in calls)

    with env.db.reader() as conn:
        steps = list(conn.execute('SELECT * FROM agent_step WHERE run_id=? ORDER BY sequence', (run['id'],)))
        assert [step['tool_name'] for step in steps] == ['public.research', 'model', 'model']
        invalid = runtime.repo.get_content(conn, auth, run['id'], steps[1]['output_ref'])
        assert invalid['adapter_error'] == 'output_invalid'
        assert invalid['validation_error']['stage'] == 'wire_schema'
        assert invalid['validation_error']['code']
        assert 'plan_item_id' in invalid['validation_error']['path']
        assert untrusted_marker not in json.dumps(invalid)
        assert calls[1]['validation_error'] == invalid['validation_error']
        usage = list(conn.execute('SELECT u.* FROM budget_usage u JOIN agent_step s ON s.hold_id=u.hold_id WHERE s.run_id=? ORDER BY s.sequence', (run['id'],)))
        assert [entry['inference_micro_usd'] for entry in usage] == [6200, 2000, 2000]
        assert all(entry['web_search_calls'] == 0 for entry in usage[1:])
        assert [entry[0] for entry in conn.execute('SELECT h.state FROM budget_hold h JOIN agent_step s ON s.hold_id=h.id WHERE s.run_id=?', (run['id'],))] == ['settled'] * 3
        assert conn.execute('SELECT COUNT(*) FROM public_research_dispatch WHERE run_id=?', (run['id'],)).fetchone()[0] == 1
        assert json.loads(result['limits_json'])['max_invalid_decisions'] == 1
    if not recover:
        assert result['reason'] == 'invalid_decision'
        runtime.advance_slice(auth, run['id'])
        assert len(calls) == 2 and len(outbound) == 2
        assert len(rows(env, 'budget_usage')) == 3
        # An explicit owner resume may try again, but never resets counters,
        # repeats research, or avoids the new model request's reservation.
        allow_correction[0] = True
        runtime.resume(auth, run['id'])
        resumed = runtime.advance_slice(auth, run['id'])
        assert resumed['status'] == 'completed'
        assert resumed['invalid_count'] == 2 and resumed['decision_count'] == 3
        assert resumed['action_count'] == 7 and resumed['public_research'] == result['public_research']
        assert len(calls) == 3 and len(outbound) == 2 and len(planner.calls) == 3
        assert [entry['inference_micro_usd'] for entry in rows(env, 'budget_usage')] == [6200, 2000, 2000, 2000]


def test_missing_evidence_receives_specific_feedback_without_reflecting_untrusted_identifiers(build_env):
    env = build_env()
    auth, instance = active(env)
    marker = 'UNTRUSTED-MISSING-REFERENCE'
    invalid = envelope(memory=[{'op': 'upsert', 'key': 'unsupported', 'kind': 'observation',
                                'text': 'A claim without evidence.', 'evidence_refs': [marker]}],
                       control={'next': 'wait_owner', 'question': 'This question must not be committed.', 'options': []})
    runtime, model, tool = setup_runtime(env, [invalid, envelope(control={
        'next': 'wait_owner', 'question': 'A valid follow-up.', 'options': []})])
    run = runtime.create_run(auth, instance.id, 'evidence-repair', definition())
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'waiting_owner' and result['invalid_count'] == 1
    assert result['checkpoint']['question']['text'] == 'A valid follow-up.'
    assert not result['checkpoint']['memory'] and not tool.calls
    feedback = model.calls[1]['validation_error']
    assert 'saved content references' in feedback and marker not in feedback


def test_coordinator_rechecks_diagnostics_and_never_forwards_exception_values():
    marker = 'UNTRUSTED-DIAGNOSTIC-INSTRUCTION'
    for diagnostic in (
        {'stage': 'wire_schema', 'code': 'invalid_variant', 'path': 'actions[0].' + marker},
        {'stage': 'wire_schema', 'code': marker, 'path': 'actions[0].plan_item_id'},
        {'stage': 'wire_schema', 'code': 'invalid_variant', 'path': 'actions[0].plan_item_id', 'message': marker},
    ):
        feedback = AgentRuntime._decision_feedback({'adapter_error': 'output_invalid', 'validation_error': diagnostic}, ValueError(marker))
        assert type(feedback) is str and marker not in feedback
        assert 'No changes' in feedback
    assert marker not in AgentRuntime._decision_feedback({}, ValueError(marker))


@pytest.mark.parametrize('draft_limit,requirements,hint', [
    (0, ['r1'], 'remaining_draft_continuations is exhausted'),
    (1, ['unknown'], 'owner requirement IDs supplied in the saved definition'),
])
def test_visible_draft_allowance_and_precise_feedback_allow_final_write_without_expanding_limits(
        build_env, draft_limit, requirements, hint):
    env = build_env()
    auth, instance = active(env)
    invalid = envelope(artifacts=[{'local_ref': 'rejected', 'content': 'Do not apply this draft.'}],
                       control={'next': 'continue_draft', 'requirement_ids': requirements, 'reason': 'More writing remains.'})
    runtime, model, tool = setup_runtime(env, [invalid, finish])
    run = runtime.create_run(auth, instance.id, 'draft-limit-repair', definition(), limits={
        'max_decisions': 2, 'max_actions': 0, 'max_draft_continuations': draft_limit})
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed' and result['invalid_count'] == 1
    assert result['decision_count'] == 2 and result['draft_count'] == result['action_count'] == 0
    assert set(result['checkpoint']['artifacts']) == {'comparison', 'summary'}
    assert not tool.calls
    assert hint in model.calls[1]['validation_error']
    assert model.calls[0]['runtime_limits'] == {
        'remaining_decisions': 1, 'remaining_actions': 0, 'remaining_draft_continuations': draft_limit}
    assert model.calls[1]['runtime_limits'] == {
        'remaining_decisions': 0, 'remaining_actions': 0, 'remaining_draft_continuations': draft_limit}
