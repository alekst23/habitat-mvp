"""Owner-visible campaign evidence and separate approval, funding, delivery states."""

from aicl.app import FIXTURE_CSRF_TOKEN
from aicl.workflow.factory import workflow_service
from test_owner_journey_pages import _create, _make_ready, _post, _schedule, _tick, _FormFields


def _example(web, instance_id):
    path = f"/instances/{instance_id}/workflow"
    page = web.owner_a.get(path)
    assert 'Use app marketing example' in page.text
    fields = _FormFields(page.text, path + '/example').fields
    result = _post(web, path + '/example', **fields)
    assert result.status_code == 303 and 'example_saved' in result.headers['location']
    return workflow_service(web.app.state.ctx)


def test_example_is_explicit_owned_and_cannot_replace_a_saved_workflow(web):
    instance_id, payments = _create(web)
    workflow = workflow_service(web.app.state.ctx)
    assert not workflow.config(web.auth_a, instance_id)['saved']
    path = f'/instances/{instance_id}/workflow/example'
    origin = {'origin': web.app.state.ctx.settings.public_base_url}
    assert web.owner_a.post(path, headers=origin, data={'expected_version': '1'}).status_code == 403
    assert web.owner_b.post(path, headers=origin, data={'csrf_token': FIXTURE_CSRF_TOKEN, 'expected_version': '1'}).status_code == 404
    _example(web, instance_id)
    before = workflow.config(web.auth_a, instance_id)
    assert before['scenario'] == 'pocketplan_ads'
    assert not before['enabled'] and not workflow.overview(web.auth_a, instance_id)['runs']
    assert payments.dashboard(web.auth_a, instance_id)['balance_micro_usd'] == 0
    repeat = _post(web, path, expected_version=before['version'])
    assert 'error=' in repeat.headers['location']
    assert workflow.config(web.auth_a, instance_id) == before
    saved = web.owner_a.get(f'/instances/{instance_id}/workflow').text
    assert 'Use app marketing example' not in saved
    assert 'name="scenario" value="pocketplan_ads"' in saved
    assert 'Campaign planning and creative are delivered before purchase approval.' in saved


def test_campaign_review_shows_evidence_scope_and_outputs_before_payment(web):
    instance_id, payments = _create(web, ('inference',))
    workflow = _example(web, instance_id)
    _make_ready(web, instance_id)
    policy = payments.dashboard(web.auth_a, instance_id)['policy']
    payments.configure(web.auth_a, instance_id, True, 5000, policy['version'])
    assert _schedule(web, instance_id, True).status_code == 303
    data = _tick(web, instance_id, workflow)
    request, = data['purchases']
    assert data['deliverables'], 'Planning and creative must not wait for payment.'
    campaign = request['quote']['campaign']
    review = web.owner_a.get(f'/audit?view=purchases&instance_id={instance_id}')
    assert review.status_code == 200
    for value in ('PocketPlan', 'LaunchPad Ads', 'Why this campaign:', 'Alternative:', 'If declined:',
                  'https://pocketplan.example/app', '$30.00 total', '$10.00/day', '3 days',
                  'View supporting output', 'Changes need a new approval.'):
        assert value in review.text
    assert '<dt>License</dt>' not in review.text and 'Paid and delivered.' not in review.text
    assert f'/audit/jobs/{request["source_job"]["id"]}' in review.text
    assert campaign['creative'][0]['headline'] in review.text
    for source in request['source_job']['supporting_work']:
        assert f'/audit/deliverables/{source["deliverable_id"]}' in review.text
    decision = _post(web, f'/audit/purchases/{request["id"]}/decision', decision='approve',
                     continuation='schedule', quote_digest=request['quote_digest'])
    order_path = decision.headers['location']
    checkout = web.owner_a.get(order_path)
    assert checkout.status_code == 200
    assert 'Prepaid advertising campaign' in checkout.text
    assert 'Ad delivery and measured spend follow separately' in checkout.text
    assert campaign['creative'][0]['headline'] in checkout.text
    _post(web, order_path + '/checkout', outcome='complete')
    receipt = web.owner_a.get(order_path)
    assert 'The campaign is funded. Payment is not proof of ad delivery' in receipt.text
    assert 'delivered template' not in receipt.text
    campaigns = web.owner_a.get(f'/audit?view=campaigns&instance_id={instance_id}')
    assert campaigns.status_code == 200 and 'Funded · not started' in campaigns.text
    assert 'No advertising delivery recorded' not in campaigns.text
    assert '$30.00' in campaigns.text and 'Ad spend consumed' in campaigns.text
    costs = web.owner_a.get(f'/audit?view=costs&instance_id={instance_id}')
    assert 'Prepaid funding and consumed ad spend are two views of the same funds' in costs.text
    assert 'Included in merchant payments above' in costs.text
