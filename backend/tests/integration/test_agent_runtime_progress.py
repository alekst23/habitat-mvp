"""Evidence progress is information, not receipts, rotating offsets or prose."""
import pytest

from aicl.agent_runtime.adapters import ScriptedTool, ToolRegistry
from test_agent_runtime_session import active, batch, definition, envelope, finish, setup_runtime


def setup_source(env, later, *, source_size=10000, limits=None):
    auth, instance = active(env)
    first = batch()
    first['actions'] = first['actions'][:1]
    tool = ScriptedTool('fixture.read', {'one': {'text': 'evidence ' * source_size}})
    runtime, model, _ = setup_runtime(env, [first, *later], ToolRegistry([tool]))
    run = runtime.create_run(auth, instance.id, 'progress', definition(), limits=limits)
    return auth, instance, runtime, model, tool, run


def read(*ranges, memory=(), artifacts=()):
    def decision(context):
        ref = next(item['ref'] for item in context['observations'] if item['tool'] == 'fixture.read')
        return envelope(actions=[{'name': 'artifact.read', 'arguments': {
            'ref': ref, 'offset': start, 'max_chars': length}} for start, length in ranges],
            memory=memory, artifacts=artifacts)
    return decision


def steps(env, run):
    with env.db.reader() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM agent_step WHERE run_id=? ORDER BY sequence', (run['id'],))]


def test_covered_reads_are_suppressed_then_can_finalize_without_new_read(build_env):
    env = build_env()
    def checked_finish(context):
        assert context['progress_feedback']['code'] == 'redundant_evidence_reads'
        assert context['progress_feedback']['skipped_read_count'] == 2
        assert context['progress_feedback']['evidence_refs']
        return finish(context)
    auth, _, runtime, model, tool, run = setup_source(env, [
        read((0, 4000)), read((100, 1000), (1500, 2000)), checked_finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    assert len(model.calls) == 4
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 1
    assert result['action_count'] == 2
    assert len([event for event in result['events'] if event['kind'] == 'reads_suppressed']) == 1
    with env.db.reader() as conn:
        assert conn.execute('SELECT COUNT(*) FROM budget_usage').fetchone()[0] == 6
        assert all(row[0] == 'settled' for row in conn.execute('SELECT state FROM budget_hold'))


def test_rotating_overlap_and_cosmetic_memory_cannot_reset_guard(build_env):
    env = build_env()
    memory = [{'op': 'upsert', 'key': 'finding', 'kind': 'assumption', 'text': 'Retained useful draft context'}]
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 2000), (2000, 2000)), read((100, 3000)), read((0, 3999), memory=memory)])
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'no_progress'
    assert len(model.calls) == 4
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 2
    assert result['checkpoint']['memory']['finding']['text'] == 'Retained useful draft context'
    assert result['checkpoint']['redundant_read_decisions'] == 2
    assert len([event for event in result['events'] if event['kind'] == 'reads_suppressed']) == 2


def test_overlap_with_unread_characters_is_allowed(build_env):
    env = build_env()
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 2000), (2000, 2000)), read((3500, 3000)), finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    assert len(model.calls) == 4
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 3
    assert not any(event['kind'] == 'reads_suppressed' for event in result['events'])


def test_failed_selection_does_not_establish_coverage(build_env):
    env = build_env()
    def bad_selection(context):
        ref = next(item['ref'] for item in context['observations'] if item['tool'] == 'fixture.read')
        return envelope(actions=[{'name': 'artifact.read', 'arguments': {'ref': ref, 'source_index': 0}}])
    auth, _, runtime, model, _, run = setup_source(env, [bad_selection, bad_selection, finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    assert len(model.calls) == 4
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 2
    assert not any(event['kind'] == 'reads_suppressed' for event in result['events'])


def test_fresh_receipts_same_information_cannot_reset_guard(build_env):
    env = build_env()
    auth, instance = active(env)
    tool = ScriptedTool('fixture.read', {'one': {'text': 'same'}, 'two': {'text': 'same'}})
    tool.cache_ttl_seconds = 0
    requests = [envelope(actions=[{'name': 'fixture.read', 'arguments': {'key': key, 'refresh': True}}])
                for key in ('one', 'two', 'one', 'two', 'one')]
    runtime, model, _ = setup_runtime(env, requests, ToolRegistry([tool]))
    run = runtime.create_run(auth, instance.id, 'same-info', definition())
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'no_progress'
    assert len(model.calls) == 4 and len(tool.calls) == 3
    receipts = [step['output_ref'] for step in steps(env, run) if step['kind'] == 'tool']
    assert len(set(receipts)) == 3
    assert model.calls[-1]['progress_feedback']['code'] == 'no_new_information'


def test_resume_keeps_guard_and_owner_message_resets_only_correction(build_env):
    env = build_env()
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 4000)), read((100, 1000)), read((200, 1000)), read((300, 1000)), finish])
    stopped = runtime.advance_slice(auth, run['id'])
    assert stopped['reason'] == 'no_progress'
    assert len(model.calls) == 4
    runtime.resume(auth, run['id'])
    still_stopped = runtime.advance_slice(auth, run['id'])
    assert still_stopped['reason'] == 'no_progress' and len(model.calls) == 5
    runtime.append_owner_message(auth, run['id'], 'Finish using the saved evidence.', 'fresh-owner-context')
    runtime.resume(auth, run['id'])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed' and len(model.calls) == 6
    assert result['checkpoint']['redundant_read_decisions'] == 0


@pytest.mark.parametrize('invalid', ['foreign_ref', 'wrong_field'])
def test_invalid_scoped_read_never_bypasses_validation_or_partly_applies(build_env, invalid):
    env = build_env()
    auth, instance = active(env)
    runtime, _, _ = setup_runtime(env, [])
    foreign = runtime.create_run(auth, instance.id, 'foreign', definition())
    def bad(context):
        ref = next(item['ref'] for item in context['observations'] if item['tool'] == 'fixture.read')
        arguments = {'ref': foreign['definition_ref']} if invalid == 'foreign_ref' else {'ref': ref, 'field': 'text'}
        return envelope(actions=[{'name': 'artifact.read', 'arguments': arguments}],
                        memory=[{'op': 'upsert', 'key': 'bad', 'kind': 'assumption', 'text': 'Must not save'}])
    auth, _, runtime, _, _, run = setup_source(env, [read((0, 4000)), bad], limits={'max_invalid_decisions': 0})
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'invalid_decision'
    assert 'bad' not in result['checkpoint']['memory']
    assert not any(event['kind'] == 'reads_suppressed' for event in result['events'])


def test_revocation_after_suppression_blocks_next_inference(build_env):
    env = build_env()
    auth, instance, runtime, model, _, run = setup_source(env, [
        read((0, 4000)), read((100, 1000)), finish])
    result = runtime.advance_slice(auth, run['id'], max_operations=5)
    assert result['checkpoint']['redundant_read_decisions'] == 1
    before = len(model.calls)
    with env.db.transaction() as conn:
        conn.execute("UPDATE capability_grant SET enabled=0 WHERE instance_id=? AND capability='inference'", (instance.id,))
        holds = conn.execute('SELECT COUNT(*) FROM budget_hold').fetchone()[0]
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'capability_disabled'
    assert len(model.calls) == before
    with env.db.reader() as conn:
        assert conn.execute('SELECT COUNT(*) FROM budget_hold').fetchone()[0] == holds


def test_same_batch_default_aliases_and_contained_ranges_execute_only_widest(build_env):
    env = build_env()
    def overlapping(context):
        ref = next(item['ref'] for item in context['observations'] if item['tool'] == 'fixture.read')
        return envelope(actions=[{'name': 'artifact.read', 'arguments': args} for args in [
            {'ref': ref}, {'ref': ref, 'offset': 0, 'max_chars': 4000},
            {'ref': ref, 'offset': 100, 'max_chars': 500, 'public_preview': False},
            {'ref': ref, 'offset': 3500, 'max_chars': 4000}]])
    auth, _, runtime, _, _, run = setup_source(env, [overlapping, finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    read_steps = [step for step in steps(env, run) if step['tool_name'] == 'artifact.read']
    assert len(read_steps) == 2
    assert [step['action_ordinal'] for step in read_steps] == [0, 3]
    assert read_steps[1]['sequence'] == read_steps[0]['sequence'] + 1
    suppressed = [event for event in result['events'] if event['kind'] == 'reads_suppressed']
    assert len(suppressed) == 1


def test_read_receipt_wrapper_cannot_manufacture_more_evidence(build_env):
    env = build_env()
    def wrapper(context):
        ref = next(item['ref'] for item in context['observations'] if item['tool'] == 'artifact.read')
        return envelope(actions=[{'name': 'artifact.read', 'arguments': {'ref': ref, 'offset': 100}}])
    auth, _, runtime, model, _, run = setup_source(env, [read((0, 4000)), wrapper, wrapper])
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'no_progress' and len(model.calls) == 4
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 1
    skipped = result['checkpoint']['progress_feedback']['skipped_reads'][0]
    assert skipped['reason'] == 'read_receipt_wrapper'
    assert skipped['source_request']['ref'] != skipped['request']['ref']


def test_identical_immutable_source_alias_is_suppressed(build_env):
    env = build_env()
    def source_alias(context):
        with env.db.transaction() as conn:
            original = next(item['ref'] for item in context['observations'] if item['tool'] == 'fixture.read')
            payload = runtime.repo.get_content(conn, auth, run['id'], original)
            alias = runtime.repo.put_content(conn, auth, run['id'], 'fixture_source', payload, identity='alias-source')
        return envelope(actions=[{'name': 'artifact.read', 'arguments': {'ref': alias, 'offset': 10, 'max_chars': 1000}}])
    auth, _, runtime, model, _, run = setup_source(env, [read((0, 4000)), source_alias, finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 1
    assert model.calls[-1]['progress_feedback']['skipped_read_count'] == 1


def test_reader_upgrade_does_not_reuse_old_projection_coverage(build_env):
    env = build_env()
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 4000)), read((0, 4000)), finish])
    runtime.advance_slice(auth, run['id'], max_operations=4)
    assert len(model.calls) == 2
    reader = runtime.tools.get('artifact.read')
    reader.version = 'artifact-v-next-fixture'
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed'
    reads = [step for step in steps(env, run) if step['tool_name'] == 'artifact.read']
    assert len(reads) == 2 and reads[0]['tool_version'] != reads[1]['tool_version']
    assert not any(event['kind'] == 'reads_suppressed' for event in result['events'])


def test_no_progress_stop_preserves_valid_artifact_write_without_counting_renaming_as_progress(build_env):
    env = build_env()
    initial = [{'local_ref': 'notes', 'content': 'Known finding', 'evidence_refs': []}]
    renamed = [{'local_ref': 'notes_copy', 'content': 'Known finding', 'evidence_refs': []}]
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 4000), artifacts=initial), read((100, 1000), artifacts=initial),
        read((200, 1000), artifacts=renamed)])
    result = runtime.advance_slice(auth, run['id'])
    assert result['reason'] == 'no_progress' and len(model.calls) == 4
    saved = result['checkpoint']['artifacts']['notes_copy']
    assert saved['version'] == 1
    assert result['checkpoint']['artifacts']['notes']['version'] == 2
    with env.db.reader() as conn:
        assert runtime.repo.get_content(conn, auth, run['id'], saved['ref'])['content'] == 'Known finding'


def test_changed_code_indentation_is_new_output_progress(build_env):
    env = build_env()
    initial = [{'local_ref': 'code', 'content': '```python\ndef f():\nreturn 1\n```', 'evidence_refs': []}]
    corrected = [{'local_ref': 'code', 'content': '```python\ndef f():\n    return 1\n```', 'evidence_refs': []}]
    auth, _, runtime, model, _, run = setup_source(env, [
        read((0, 4000), artifacts=initial), read((100, 1000)),
        read((200, 1000), artifacts=corrected), finish])
    result = runtime.advance_slice(auth, run['id'])
    assert result['status'] == 'completed' and len(model.calls) == 5
    assert result['checkpoint']['artifacts']['code']['version'] == 2
    assert len([step for step in steps(env, run) if step['tool_name'] == 'artifact.read']) == 1
    with env.db.reader() as conn:
        saved = result['checkpoint']['artifacts']['code']['ref']
        assert runtime.repo.get_content(conn, auth, run['id'], saved)['content'] == corrected[0]['content']
