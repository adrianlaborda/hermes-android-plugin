import pytest

from hermes_android import reminders

_actual_enabled = reminders.mobile_reminders_enabled


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(reminders, 'mobile_reminders_enabled', lambda: True)


@pytest.mark.parametrize('platform', ['desktop', 'api_server', 'telegram', 'hermes_android'])
def test_new_reminder_preserves_origin_on_every_surface(platform):
    args = {'action': 'create', 'schedule': 'tomorrow at noon', 'prompt': 'Do X'}
    result = reminders.route_reminder(tool_name='cronjob', args=args, platform=platform)
    assert result['args'] == dict(args, deliver='origin,hermes_android:home')
    assert 'deliver' not in args


@pytest.mark.parametrize('delivery', ['telegram:123:456', ['telegram:123', 'discord:456'], 'bot-chat:work'])
def test_preserves_original_destinations(delivery):
    from tools.cronjob_job_args import _normalize_deliver_param
    changed = reminders.with_mobile_target(delivery)
    assert changed == _normalize_deliver_param(delivery) + ',hermes_android:home'
    assert reminders.with_mobile_target(changed) == changed


@pytest.mark.parametrize('delivery', ['local', 'all', 'origin,all', 'hermes_android',
                                     'hermes_android:device-a', 'origin,hermes_android:home'])
def test_no_duplicate_or_widened_or_silent_destinations(delivery):
    assert reminders.with_mobile_target(delivery) == delivery


def test_update_preserves_stored_target_and_failure_opt_out():
    assert reminders.route_reminder(tool_name='cronjob', args={'action': 'update', 'prompt': 'new'}) is None
    result = reminders.route_reminder(tool_name='cronjob', args={
        'action': 'update', 'deliver': 'telegram:123', 'failure_deliver': 'local'})
    assert result['args']['deliver'] == 'telegram:123,hermes_android:home'
    assert result['args']['failure_deliver'] == 'local'


@pytest.mark.parametrize('action', ['list', 'run', 'pause', 'resume', 'remove'])
def test_read_and_control_actions_unchanged(action):
    assert reminders.route_reminder(tool_name='cronjob', args={'action': action}) is None


def test_disabled_and_other_tools_unchanged(monkeypatch):
    assert reminders.route_reminder(tool_name='terminal', args={'action': 'create'}) is None
    monkeypatch.setattr(reminders, 'mobile_reminders_enabled', lambda: False)
    assert reminders.route_reminder(tool_name='cronjob', args={'action': 'create'}) is None


def test_official_middleware_contract(monkeypatch):
    from hermes_cli.middleware import apply_tool_request_middleware
    from hermes_cli import plugins
    monkeypatch.setattr(plugins, 'has_middleware', lambda kind: kind == 'tool_request')
    monkeypatch.setattr(plugins, 'invoke_middleware', lambda kind, **kw: [reminders.route_reminder(**kw)])
    result = apply_tool_request_middleware('cronjob', {'action': 'create', 'prompt': 'Do X'})
    assert result.changed
    assert result.payload['deliver'] == 'origin,hermes_android:home'
    assert 'deliver' not in result.original_payload


def test_official_resolver_keeps_original_and_deduplicates_mobile(monkeypatch):
    from cron import scheduler_delivery as delivery
    from gateway.platform_registry import PlatformEntry, platform_registry
    platform_registry.register(PlatformEntry(name='hermes_android', label='test',
        adapter_factory=lambda c: None, check_fn=lambda: True, source='builtin'))
    # Exercise the official fanout/dedup implementation with real explicit targets.
    job = {'deliver': reminders.with_mobile_target('telegram:123,telegram:123'),
           'origin': {'platform': 'telegram', 'chat_id': '123'}}
    try:
        targets = delivery._resolve_delivery_targets(job)
    finally:
        platform_registry.unregister('hermes_android')
    assert [(t['platform'], t['chat_id']) for t in targets] == [
        ('telegram', '123'), ('hermes_android', 'home')]


def test_registration_uses_real_middleware():
    from hermes_android.adapter import register
    captured = {}
    class Context:
        def register_platform(self, **kwargs): pass
        def register_middleware(self, kind, handler): captured[kind] = handler
    register(Context())
    assert captured == {'tool_request': reminders.route_reminder}


def test_yaml_boolean_switch_is_preserved():
    from hermes_android.adapter import _apply_yaml_config
    assert _apply_yaml_config({}, {'mirror_reminders': False}) == {'mirror_reminders': False}
    assert 'mirror_reminders' not in _apply_yaml_config({}, {'mirror_reminders': 'false'})


def test_pairing_and_config_are_profile_scoped(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gateway import config
    from gateway.platform_registry import PlatformEntry, platform_registry
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_android.store import DeviceStore
    platform_registry.register(PlatformEntry(name='hermes_android', label='test',
        adapter_factory=lambda c: None, check_fn=lambda: True, source='builtin'))
    cfg = config.PlatformConfig(enabled=True, extra={})
    monkeypatch.setattr(config, 'load_gateway_config', lambda: SimpleNamespace(
        platforms={config.Platform('hermes_android'): cfg}))
    token = set_hermes_home_override(str(tmp_path / 'a'))
    try:
        assert not _actual_enabled()
        DeviceStore().register(device_id=None, device_secret=None, label='phone',
                                  push_type='fcm', push_token='synthetic')
        assert _actual_enabled()
        other = set_hermes_home_override(str(tmp_path / 'b'))
        try:
            assert not _actual_enabled()
        finally:
            reset_hermes_home_override(other)
        cfg.extra['mirror_reminders'] = False
        assert not _actual_enabled()
        cfg.extra.clear()
        cfg.enabled = False
        assert not _actual_enabled()
    finally:
        reset_hermes_home_override(token)
        platform_registry.unregister('hermes_android')
