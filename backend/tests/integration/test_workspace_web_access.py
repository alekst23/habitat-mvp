"""One owner policy replaces hand-configured searches without widening old grants."""
import json

import pytest

from aicl.agent_workspace.assistant import WorkspaceAssistantTools
from aicl.control.errors import AiclError
from aicl.creation.operations import SqliteInstanceOperations
from test_agent_workspace import apply, draft, setup, with_search


def configured(build_env, access):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state['id'], state['version'], {
        **draft(), 'goal': 'Find recent public AI news\nand link original reporting.',
        'inputs': 'PRIVATE-CANARY-INPUTS must stay inside analysis',
        'public_research': {'purpose': '', 'queries': [], 'source_urls': []},
        'web_access': access,
    }, actor='assistant')
    return env, auth, instance, service, state


def release(env, workspace_id):
    with env.db.reader() as conn:
        return dict(conn.execute('SELECT * FROM workspace_public_research_release WHERE workspace_id=? AND revoked_at IS NULL', (workspace_id,)).fetchone())


@pytest.mark.parametrize('access', [
    {'mode': 'all', 'domains': []},
    {'mode': 'allowlist', 'domains': [' Example.COM ', 'example.com']},
    {'mode': 'blocklist', 'domains': ['blocked.example']},
])
def test_levels_publish_goal_only_and_derive_network_grants(build_env, access):
    env, auth, instance, service, state = configured(build_env, access)
    assert set(state['draft']['tools']) == {'web.search', 'web.read'}
    assert state['public_research_release']['approval_required']
    assert not state['public_research_release']['legacy']
    with pytest.raises(AiclError) as denied:
        service.apply(auth, state['id'], state['version'])
    assert denied.value.extra['reason'] == 'confirmation_required'
    state = apply(service, auth, state)
    saved = release(env, state['id'])
    payload = json.loads(saved['payload_json'])
    assert payload['mode'] == 'agent'
    assert payload['purpose'] == state['draft']['goal']
    assert payload['queries'] == payload['source_urls'] == []
    assert payload['access'] == state['draft']['web_access']
    assert 'PRIVATE-CANARY' not in saved['payload_json']
    assert json.loads(saved['binding_json'])['planner']['model'] == 'gpt-6-sol'
    with env.db.reader() as conn:
        grants = {r[0] for r in conn.execute('SELECT capability FROM capability_grant WHERE instance_id=? AND enabled=1', (instance.id,))}
        assert {'inference', 'network.search', 'network.fetch'} <= grants
        assert conn.execute('SELECT COUNT(*) FROM agent_run').fetchone()[0] == 0
    assert state['draft']['network_domains'] == (['example.com'] if access['mode'] == 'allowlist' else [])


def test_private_edits_preserve_release_but_goal_and_scope_changes_require_review(build_env):
    env, auth, _, service, state = configured(build_env, {'mode': 'all', 'domains': []})
    state = apply(service, auth, state)
    old = release(env, state['id'])
    # Existing bundled policies retain their signed payload while merely viewed
    # or privately edited; exposing a new control must not invalidate approval.
    assert 'search_access' not in json.loads(old['payload_json'])
    assert service.view(auth, state['id'])['draft']['web_search'] is None
    assert release(env, state['id']) == old
    state = service.update_draft(auth, state['id'], state['version'], {'inputs': 'Different PRIVATE-CANARY'})
    assert not state['public_research_release']['approval_required']
    state = service.apply(auth, state['id'], state['version'])
    assert release(env, state['id']) == old
    for patch in [{'goal': 'Find public robotics research'}, {'web_access': {'mode': 'blocklist', 'domains': ['blocked.example']}}]:
        state = service.update_draft(auth, state['id'], state['version'], patch)
        assert state['public_research_release']['approval_required']
        with pytest.raises(AiclError):
            service.apply(auth, state['id'], state['version'], approved_public_research_digest=old['disclosure_digest'])
        assert release(env, state['id']) == old
    state = apply(service, auth, state)
    assert release(env, state['id'])['version'] == 2


def test_off_revokes_web_access_and_hidden_tool_fields_cannot_reenable_it(build_env):
    env, auth, instance, service, state = configured(build_env, {'mode': 'all', 'domains': []})
    state = apply(service, auth, state)
    state = service.update_draft(auth, state['id'], state['version'], {
        'web_access': {'mode': 'off', 'domains': []}, 'tools': ['web.read', 'web.search'],
    })
    assert state['draft']['tools'] == []
    assert not state['public_research_release']['approval_required']
    state = service.apply(auth, state['id'], state['version'])
    with env.db.reader() as conn:
        assert not conn.execute('SELECT 1 FROM workspace_public_research_release WHERE workspace_id=? AND revoked_at IS NULL', (state['id'],)).fetchone()
        assert not conn.execute("SELECT 1 FROM capability_grant WHERE instance_id=? AND enabled=1 AND capability IN ('network.search','network.fetch')", (instance.id,)).fetchone()


def test_empty_goal_and_allowlist_remain_editable_without_approvable_digest(build_env):
    env, auth, _, service, state = configured(build_env, {'mode': 'allowlist', 'domains': []})
    assert state['public_research_release']['draft_digest'] is None
    with pytest.raises(AiclError, match='validation_failed'):
        apply(service, auth, state)
    state = service.update_draft(auth, state['id'], state['version'], {'web_access': {'mode': 'all', 'domains': []}, 'goal': ''})
    assert state['public_research_release']['draft_digest'] is None
    with pytest.raises(AiclError, match='validation_failed'):
        apply(service, auth, state)


def test_legacy_release_is_preserved_until_explicit_policy_approval(build_env):
    env, auth, instance, service = setup(build_env)
    with_search(service)
    state = service.open(auth, instance_id=instance.id)
    state = service.update_draft(auth, state['id'], state['version'], draft())
    state = apply(service, auth, state)
    old = release(env, state['id'])
    viewed = service.view(auth, state['id'])
    assert viewed['draft']['web_access'] is None
    assert viewed['public_research_release']['legacy']
    assert release(env, state['id']) == old
    state = service.update_draft(auth, state['id'], state['version'], {'web_access': {'mode': 'all', 'domains': []}})
    assert state['public_research_release']['approval_required']
    with pytest.raises(AiclError):
        service.apply(auth, state['id'], state['version'], approved_public_research_digest=old['disclosure_digest'])
    assert release(env, state['id']) == old


def test_assistant_offers_policy_not_exact_network_payloads():
    update = next(tool for tool in WorkspaceAssistantTools.schemas() if tool['name'] == 'update_draft')
    fields = update['parameters']['properties']['patch']['properties']
    assert {'web_access', 'web_search'} <= set(fields)
    assert 'public_research' not in fields
    assert 'network_domains' not in fields
    read = next(tool for tool in WorkspaceAssistantTools.schemas() if tool['name'] == 'read_workspace')
    assert {'web_access', 'web_search', 'public_research', 'network_domains'} <= set(read['parameters']['properties']['section']['enum'])
    assert not {'apply', 'approve', 'approved_public_research_digest'} & {tool['name'] for tool in WorkspaceAssistantTools.schemas()}


@pytest.mark.parametrize(('page_access', 'search_access', 'tools', 'grants'), [
    ({'mode': 'off', 'domains': []}, {'mode': 'allowlist', 'domains': [' News.Example ']},
     {'web.search'}, {'network.search'}),
    ({'mode': 'allowlist', 'domains': ['articles.example']}, {'mode': 'off', 'domains': []},
     {'web.read'}, {'network.fetch'}),
    ({'mode': 'allowlist', 'domains': ['articles.example']}, {'mode': 'blocklist', 'domains': ['ads.example']},
     {'web.read', 'web.search'}, {'network.fetch', 'network.search'}),
])
def test_search_and_page_policies_publish_independently(build_env, page_access, search_access, tools, grants):
    env, auth, instance, service, state = configured(build_env, page_access)
    state = service.update_draft(auth, state['id'], state['version'], {'web_search': search_access}, actor='assistant')
    assert set(state['draft']['tools']) == tools
    with pytest.raises(AiclError) as denied:
        service.apply(auth, state['id'], state['version'])
    assert denied.value.extra['reason'] == 'confirmation_required'
    state = apply(service, auth, state)
    payload = json.loads(release(env, state['id'])['payload_json'])
    assert payload['access'] == state['draft']['web_access']
    assert payload['search_access'] == state['draft']['web_search']
    assert state['draft']['network_domains'] == page_access['domains']
    assert state['published']['tools'] == state['draft']['tools']
    with env.db.reader() as conn:
        actual = {row[0] for row in conn.execute("SELECT capability FROM capability_grant WHERE instance_id=? AND enabled=1 AND capability IN ('network.search','network.fetch')", (instance.id,))}
        assert actual == grants
        assert conn.execute('SELECT COUNT(*) FROM agent_run').fetchone()[0] == 0


def test_search_changes_need_current_owner_approval_and_off_preserves_pages(build_env):
    env, auth, instance, service, state = configured(build_env, {'mode': 'allowlist', 'domains': ['articles.example']})
    state = service.update_draft(auth, state['id'], state['version'], {'web_search': {'mode': 'allowlist', 'domains': ['news.example']}})
    state = apply(service, auth, state)
    old = release(env, state['id'])
    assistant = WorkspaceAssistantTools(service.ctx, auth, state['id'], state['version'])
    assistant.invoke('update_draft', {'expected_version': state['version'], 'patch': {'web_search': {'mode': 'all', 'domains': []}}})
    state = service.view(auth, state['id'])
    assert state['public_research_release']['approval_required']
    with pytest.raises(AiclError, match='denied'):
        assistant.invoke('apply', {'approved_public_research_digest': state['public_research_release']['draft_digest']})
    with pytest.raises(AiclError):
        service.apply(auth, state['id'], state['version'], approved_public_research_digest=old['disclosure_digest'])
    assert release(env, state['id']) == old
    state = apply(service, auth, state)
    state = service.update_draft(auth, state['id'], state['version'], {
        'web_search': {'mode': 'off', 'domains': []}, 'tools': ['web.read', 'web.search'],
    })
    assert state['draft']['tools'] == ['web.read']
    state = apply(service, auth, state)
    assert state['published']['web_access'] == {'mode': 'allowlist', 'domains': ['articles.example']}
    with env.db.reader() as conn:
        grants = dict(conn.execute("SELECT capability,enabled FROM capability_grant WHERE instance_id=? AND capability IN ('network.search','network.fetch')", (instance.id,)))
    assert grants == {'network.search': 0, 'network.fetch': 1}


@pytest.mark.parametrize('search_access', [None, {'mode': 'allowlist', 'domains': ['news.example']}])
def test_reload_of_revoked_search_preserves_page_scope_without_broadening(build_env, search_access):
    env, auth, instance, service, state = configured(build_env, {'mode': 'allowlist', 'domains': ['articles.example']})
    if search_access is not None:
        state = service.update_draft(auth, state['id'], state['version'], {'web_search': search_access})
    state = apply(service, auth, state)
    with env.db.reader() as conn:
        version = conn.execute('SELECT version FROM agent_instance WHERE id=?', (instance.id,)).fetchone()[0]
    SqliteInstanceOperations(env.db, env.clock).set_capability(auth, instance.id, version, 'network.search', False)
    assert service.view(auth, state['id'])['external_conflict']
    state = service.reload(auth, state['id'], state['version'])
    assert state['draft']['web_search'] == {'mode': 'off', 'domains': []}
    assert state['draft']['web_access'] == {'mode': 'allowlist', 'domains': ['articles.example']}
    assert state['draft']['tools'] == ['web.read']
    state = apply(service, auth, state)
    with env.db.reader() as conn:
        grants = dict(conn.execute("SELECT capability,enabled FROM capability_grant WHERE instance_id=? AND capability IN ('network.search','network.fetch')", (instance.id,)))
    assert grants == {'network.search': 0, 'network.fetch': 1}
