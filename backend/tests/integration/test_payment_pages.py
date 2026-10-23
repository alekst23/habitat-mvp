"""Owner-facing recovery across the app and independent mock HTTP payment API."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from aicl.app import FIXTURE_CSRF_TOKEN, FIXTURE_OWNERS, create_app
from aicl.commerce import payment_client
from aicl.commerce.factory import commerce_service
from aicl.commerce.payment_api import create_payment_app
from aicl.control.auth import AuthContext
from aicl.settings import Settings
from test_payment_api import LocalApiTransport, TOKEN


def test_remembered_buyer_forms_are_owned_and_return_funding_to_same_agent(web):
    from test_owner_journey_pages import _create, _post

    instance_id, service = _create(web)
    canonical = f'/instances/{instance_id}'
    topup = _post(web, canonical + '/commerce/topups', amount_minor='500', request_id='buyer-funding')
    path = topup.headers['location']
    page = web.owner_a.get(path)
    assert 'Choose an account' in page.text
    missing = _post(web, path + '/checkout', outcome='complete')
    assert 'buyer_required' in missing.headers['location']
    assert service.dashboard(web.auth_a, instance_id)['balance_micro_usd'] == 0

    origin = {'origin': web.app.state.ctx.settings.public_base_url}
    fields = {'csrf_token': FIXTURE_CSRF_TOKEN, 'buyer_id': 'demo-buyer'}
    assert web.owner_a.post(path + '/buyer', headers=origin, data={'buyer_id': 'demo-buyer'}).status_code == 403
    assert web.owner_b.post(path + '/buyer', headers=origin, data=fields).status_code == 404
    with TestClient(web.app) as anonymous:
        assert anonymous.post(path + '/buyer', headers=origin, data=fields).status_code == 401
    chosen = _post(web, path + '/buyer', buyer_id='demo-buyer')
    assert chosen.headers['location'] == path
    assert 'PayPal · Demo buyer' in web.owner_a.get(path).text
    assert service.payment_profile(web.auth_b) is None

    paid = _post(web, path + '/checkout', outcome='complete', buyer_id='demo-buyer')
    assert paid.headers['location'].startswith(canonical + '?') and paid.headers['location'].endswith('#setup')
    assert 'Service credit is available' in web.owner_a.get(paid.headers['location']).text
    next_topup = _post(web, canonical + '/commerce/topups', amount_minor='500', request_id='buyer-reuse')
    next_page = web.owner_a.get(next_topup.headers['location']).text
    assert 'PayPal · Demo buyer' in next_page and 'Choose an account' not in next_page
    assert 'Change account' in next_page
    next_path = next_topup.headers['location']
    older = _post(web, canonical + '/commerce/topups', amount_minor='500', request_id='keep-original-buyer')
    _post(web, next_path + '/buyer', buyer_id='demo-buyer-alt', expected_buyer_id='demo-buyer')
    stale = _post(web, next_path + '/checkout', outcome='complete', buyer_id='demo-buyer')
    assert 'buyer_changed' in stale.headers['location']
    assert service.dashboard(web.auth_a, instance_id)['balance_micro_usd'] == 5_000_000
    assert service.payment_profile(web.auth_a)['buyer_id'] == 'demo-buyer-alt'
    _post(web, older.headers['location'] + '/checkout', outcome='complete', buyer_id='demo-buyer')
    assert service.payment_profile(web.auth_a)['buyer_id'] == 'demo-buyer-alt'


def test_http_checkout_lost_response_exposes_safe_owned_status_recovery(base_env, tmp_path, monkeypatch):
    transport = LocalApiTransport(create_payment_app(tmp_path / 'provider.db', TOKEN), lose_capture_once=True)
    real_adapter = payment_client.HttpMockPaymentAdapter
    monkeypatch.setattr(payment_client, 'HttpMockPaymentAdapter',
        lambda url, token, **kwargs: real_adapter(url, token, transport=transport, **kwargs))
    settings = Settings.from_env({**base_env, 'AICL_ENVIRONMENT': 'test', 'AICL_TEST_MODE': '1',
        'AICL_MOCK_PAYMENT_API_URL': 'http://127.0.0.1:4174', 'AICL_MOCK_PAYMENT_TOKEN': TOKEN})
    app = create_app(settings)
    headers = {'origin': settings.public_base_url}
    owner_id = FIXTURE_OWNERS['owner-a']
    auth = AuthContext(owner_id, owner_id, 's-owner-a', datetime(2100, 1, 1, tzinfo=timezone.utc))
    with TestClient(app) as owner, TestClient(app) as other, TestClient(app) as anonymous:
        owner.post('/__test__/seed-session', json={'fixture': 'owner-a'})
        other.post('/__test__/seed-session', json={'fixture': 'owner-b'})
        created = owner.post('/app-tools/create_instance', headers={**headers, 'x-csrf-token': FIXTURE_CSRF_TOKEN},
            json={'idempotency_key': 'wiz_' + '9' * 32, 'template_id': 'default', 'name': 'API recovery',
                  'instructions': 'Test payment status.', 'enabled_capabilities': []})
        assert created.status_code == 200
        instance_id = created.json()['instance']['id']
        topup = owner.post(f'/instances/{instance_id}/commerce/topups', headers=headers,
            data={'csrf_token': FIXTURE_CSRF_TOKEN, 'amount_minor': '500', 'request_id': 'http-topup'},
            follow_redirects=False)
        order_path = topup.headers['location']
        assert 'Demo checkout — no real charges.' in owner.get(order_path).text
        result = owner.post(order_path + '/checkout', headers=headers,
            data={'csrf_token': FIXTURE_CSRF_TOKEN, 'outcome': 'complete', 'buyer_id': 'demo-buyer'}, follow_redirects=False)
        assert result.status_code == 303 and result.headers['location'].startswith(order_path)
        page = owner.get(result.headers['location'])
        assert 'Payment result needs checking' in page.text
        assert '>Check payment status</button>' in page.text
        assert 'name="outcome" value="complete"' not in page.text
        service = commerce_service(app.state.ctx)
        assert service.dashboard(auth, instance_id)['balance_micro_usd'] == 0
        order_id = order_path.rsplit('/', 1)[1]
        remote = service.payments.status(service.order(auth, order_id))
        assert remote['status'] == 'COMPLETED'
        recovery = order_path + '/reconcile'
        fields = {'csrf_token': FIXTURE_CSRF_TOKEN}
        assert owner.post(recovery, headers=headers).status_code == 403
        assert anonymous.post(recovery, headers=headers, data=fields).status_code == 401
        assert other.post(recovery, headers=headers, data=fields).status_code == 404
        resolved = owner.post(recovery, headers=headers, data=fields, follow_redirects=False)
        assert resolved.status_code == 303 and resolved.headers['location'].endswith('#setup')
        receipt = owner.get(order_path)
        assert remote['capture_id'] in receipt.text and 'Payment completed' in receipt.text
        owner.post(recovery, headers=headers, data=fields)
        owner.post(order_path + '/checkout', headers=headers, data={**fields, 'outcome': 'complete', 'buyer_id': 'demo-buyer'})
        final = service.dashboard(auth, instance_id)
        assert final['balance_micro_usd'] == 5_000_000 and len(final['receipts']) == 1
