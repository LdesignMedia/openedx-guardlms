import json
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client, override_settings
from django.utils import timezone
from guardlms_openedx.models import Connection
from guardlms_openedx.state import decrypt, encrypt
from guardlms_openedx.transport import DeliveryError, https_origin
from guardlms_openedx.tasks import push

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolate_callback_sdk_refresh():
    with patch('guardlms_openedx.views.refresh_sdk') as refresh:
        yield refresh


@pytest.fixture
def admin(django_user_model):
    user = django_user_model.objects.create_superuser('admin', 'admin@example.test', 'test-only-password')
    client = Client(HTTP_HOST='openedx.example.test')
    client.force_login(user)
    return client


@pytest.fixture
def connected():
    return Connection.objects.create(credentials=encrypt({
        'token': 'inventory-private-key', 'website_id': 42,
        'sdk': {'key': 'browser-key', 'enabled': True, 'subscription_active': True,
                'sdk_url': 'https://api.guardlms.test/sdk/guardlms.min.js',
                'errors_endpoint': 'https://api.guardlms.test/api/sdk/errors/collect',
                'analytics_endpoint': 'https://api.guardlms.test/api/sdk/analytics/collect',
                'analytics_allowed': False},
    }), site_url='https://openedx.example.test')


def test_secret_encryption(connected):
    assert 'inventory-private-key' not in connected.credentials
    assert decrypt(connected.credentials)['token'] == 'inventory-private-key'


@pytest.mark.parametrize('path', ['', 'preview', 'callback?code=fake&state=fake'])
def test_anonymous_administrator_endpoints_are_forbidden(client, path):
    assert client.get('/guardlms/' + path).status_code == 403


def test_non_superuser_cannot_manage(client, django_user_model):
    user = django_user_model.objects.create_user('learner', password='test-only-password')
    client.force_login(user)
    assert client.get('/guardlms/').status_code == 403
    assert client.post('/guardlms/disconnect').status_code == 403


def test_csrf_required(django_user_model):
    user = django_user_model.objects.create_superuser('admin', 'a@example.test', 'test-only-password')
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.post('/guardlms/connect').status_code == 403


def begin(admin):
    response = admin.post('/guardlms/connect', HTTP_HOST='openedx.example.test')
    assert response.status_code == 302
    return parse_qs(urlsplit(response.url).query)['state'][0]


def test_connect_callback_and_replay(admin):
    state = begin(admin)
    data = {'token': 'private', 'siteurl': 'https://openedx.example.test', 'pushpath': '/api/externalpush/openedx', 'website_id': 42}
    with patch('guardlms_openedx.views.send', return_value={'data': data}), patch('guardlms_openedx.tasks.push', return_value=True):
        assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}).status_code == 302
        assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}).status_code == 403
    assert decrypt(Connection.current().credentials)['token'] == 'private'


def test_failed_exchange_returns_safe_retry(admin):
    state = begin(admin)
    with patch('guardlms_openedx.views.send', side_effect=DeliveryError(503)):
        response = admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}, follow=True)
    assert b'Start a new connection attempt' in response.content
    assert not Connection.current().credentials


def test_disconnect_invalidates_pending_callback(admin, connected):
    state = begin(admin)
    admin.post('/guardlms/disconnect')
    with patch('guardlms_openedx.views.send') as exchange:
        assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}).status_code == 403
        exchange.assert_not_called()
    assert not Connection.current().credentials


def test_expired_state_and_wrong_state_refused(admin):
    state = begin(admin)
    assert admin.get('/guardlms/callback', {'state': 'wrong', 'code': 'x' * 64}).status_code == 403
    session = admin.session
    session['guardlms_connect'] = dict(session['guardlms_connect'], created=time.time() - 601)
    session.save()
    assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}).status_code == 403


def test_reporting_schedule_backoff_and_recovery(connected):
    with patch('guardlms_openedx.inventory.collect', return_value={}), patch('guardlms_openedx.tasks.send', side_effect=DeliveryError(401)):
        assert not push(force=True)
        refused = Connection.current().first_refused
        assert refused
        assert Connection.current().credentials == connected.credentials
        assert not push()
        assert not push(force=True)
        assert Connection.current().first_refused == refused
        assert Connection.current().next_attempt > timezone.now() + timedelta(seconds=100)
    with patch('guardlms_openedx.inventory.collect', return_value={}), patch('guardlms_openedx.tasks.send', side_effect=[{'data': {'components_upserted': 7}}, {'data': {'key': None, 'enabled': True}}]):
        assert push(force=True)
    state = Connection.current()
    assert state.first_refused is None
    assert state.next_attempt > timezone.now() + timedelta(hours=23)
    assert state.component_count == 7
    assert decrypt(state.credentials)['sdk']['key'] == 'browser-key'


def test_clone_does_not_send(connected):
    with override_settings(GUARDLMS_SITE_URL='https://clone.example.test'), patch('guardlms_openedx.tasks.send') as send:
        assert not push(force=True)
        send.assert_not_called()


def test_preferences_and_public_config(admin, connected):
    assert admin.get('/guardlms/browser-config', HTTP_ORIGIN='https://evil.example.test').status_code == 403
    response = admin.get('/guardlms/browser-config', HTTP_ORIGIN='https://apps.example.test')
    assert response['Access-Control-Allow-Origin'] == 'https://apps.example.test'
    assert response['Cache-Control'] == 'no-store'
    config = response.json()
    assert config['apiKey'] == 'browser-key'
    assert 'inventory-private-key' not in response.content.decode()
    assert config['autoDetectErrors']
    admin.post('/guardlms/preferences', {'browser_errors': 'on', 'analytics': 'on'})
    assert not admin.get('/guardlms/browser-config').json()['analytics']['enabled']
    admin.post('/guardlms/preferences', {})
    assert admin.get('/guardlms/browser-config').json() == {}


def test_telemetry_opt_in_and_redaction(connected):
    from guardlms_openedx.telemetry import report_exception
    with patch('guardlms_openedx.telemetry.send') as send:
        report_exception(ValueError('learner@example.test password=secret'))
        send.assert_not_called()
        connected.server_errors = True
        connected.save()
        try:
            raise DatabaseError("SELECT secret FROM learner WHERE password='private'")
        except DatabaseError as error:
            report_exception(error)
        payload = send.call_args.args[1]
        assert payload['errors'][0]['type'] == 'sql'
        assert 'private' not in json.dumps(payload)
        assert 'SELECT' not in json.dumps(payload)
        assert 'learner' not in json.dumps(payload)


def test_telemetry_failures_are_swallowed(connected):
    from guardlms_openedx.telemetry import report_exception
    connected.server_errors = True
    connected.save()
    with patch('guardlms_openedx.telemetry.send', side_effect=DeliveryError(500)) as send:
        report_exception(ValueError('secret'))
        assert send.call_count == 1


@pytest.mark.parametrize('origin', ['http://example.test', 'https://user:secret@example.test', 'https://example.test/path', 'https://example.test?next=x'])
def test_https_origin_validation(origin):
    with pytest.raises(ValueError):
        https_origin(origin)


def test_inventory_requires_manifest_and_no_sensitive_settings(tmp_path):
    from guardlms_openedx.inventory import collect, normalized_name
    manifest = tmp_path / 'npm.json'
    with override_settings(GUARDLMS_MFE_MANIFEST=str(manifest)):
        with pytest.raises(RuntimeError):
            collect()
        manifest.write_text('[]')
        payload = collect()
    assert payload['openedx']['version'] == 'release/verawood.2'
    assert payload['django']['version']
    assert 'SECRET_KEY' not in json.dumps(payload)
    assert normalized_name('Django__REST.Framework') == 'django-rest-framework'


def test_lost_browser_key_is_rotated_on_refresh(connected):
    data = decrypt(connected.credentials)
    data['sdk'] = None
    connected.credentials = encrypt(data)
    connected.save()
    with patch('guardlms_openedx.inventory.collect', return_value={}), patch('guardlms_openedx.tasks.send', side_effect=[{'data': {'components_upserted': 1}}, {'data': {'key': 'fresh-browser-key'}}]) as send:
        assert push(force=True)
        assert send.call_args_list[1].args[1]['action'] == 'rotate'
    assert decrypt(Connection.current().credentials)['sdk']['key'] == 'fresh-browser-key'


def test_changed_browser_key_prefix_is_recovered(connected):
    with patch('guardlms_openedx.inventory.collect', return_value={}), patch('guardlms_openedx.tasks.send', side_effect=[{'data': {'components_upserted': 1}}, {'data': {'key': None, 'key_prefix': 'different'}}, {'data': {'key': 'recovered-browser-key'}}]) as send:
        assert push(force=True)
        assert send.call_args_list[2].args[1]['action'] == 'rotate'
    assert decrypt(Connection.current().credentials)['sdk']['key'] == 'recovered-browser-key'


def test_corrupt_credentials_show_recovery_and_do_not_expose_errors(admin, connected):
    connected.credentials = 'unreadable-ciphertext'
    connected.save()
    assert b'Reconnect required' in admin.get('/guardlms/').content
    assert admin.get('/guardlms/browser-config').json() == {}
    assert not push(force=True)
    assert Connection.current().last_error


def test_failed_first_report_keeps_successful_connection(admin):
    state = begin(admin)
    data = {'token': 'private', 'siteurl': 'https://openedx.example.test', 'pushpath': '/api/externalpush/openedx', 'website_id': 42}
    with patch('guardlms_openedx.views.send', return_value={'data': data}), patch('guardlms_openedx.tasks.push', return_value=False):
        response = admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}, follow=True)
    assert b'will retry automatically' in response.content
    assert decrypt(Connection.current().credentials)['token'] == 'private'


def test_callback_registers_browser_origins_even_if_inventory_fails(admin, isolate_callback_sdk_refresh):
    state = begin(admin)
    data = {'token': 'private', 'siteurl': 'https://openedx.example.test', 'pushpath': '/api/externalpush/openedx', 'website_id': 42}
    with patch('guardlms_openedx.views.send', return_value={'data': data}), patch('guardlms_openedx.tasks.push', return_value=False):
        assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}).status_code == 302
    isolate_callback_sdk_refresh.assert_called_once_with(data)


def test_native_monitoring_controls_have_dutch_translations(admin):
    from django.utils.translation import override
    with override('nl'):
        response = admin.get('/guardlms/')
    assert 'Browserfouten rapporteren' in response.content.decode()
    assert 'Niet gekoppeld' in response.content.decode()


def test_security_checks_aggregate_studio_and_preserve_unknown():
    from types import SimpleNamespace
    from guardlms_openedx.inventory import deployment_security_checks
    local = {"debug": "ok", "cors": "warning", "https": "ok"}
    with override_settings(GUARDLMS_STUDIO_SETTINGS_MODULE="cms.envs.tutor.production"), patch("guardlms_openedx.inventory.security_checks", return_value=local):
        with patch("guardlms_openedx.inventory.subprocess.run", return_value=SimpleNamespace(stdout='GUARDLMS_CHECKS={"debug":"warning","cors":"ok","https":"ok"}')):
            assert deployment_security_checks() == {"debug":"warning", "cors":"warning", "https":"ok"}
        with patch("guardlms_openedx.inventory.subprocess.run", side_effect=OSError):
            assert deployment_security_checks() == {"debug":"unknown", "cors":"warning", "https":"unknown"}


def test_callback_is_restricted_to_canonical_lms_host(admin):
    state = begin(admin)
    with patch('guardlms_openedx.views.send') as exchange:
        assert admin.get('/guardlms/callback', {'state': state, 'code': 'x' * 64}, HTTP_HOST='testserver').status_code == 403
        exchange.assert_not_called()
    assert 'guardlms_connect' in admin.session


@pytest.mark.parametrize('regexes,expected', [(['.*'], 'warning'), (['^https://trusted[0-9]+.example$'], 'unknown')])
def test_cors_regex_configuration_is_not_falsely_passed(regexes, expected):
    from guardlms_openedx.inventory import security_checks
    with override_settings(CORS_ALLOWED_ORIGIN_REGEXES=regexes):
        assert security_checks()['cors'] == expected
