import pytest


@pytest.fixture(autouse=True)
def isolate_jev_settings(request, tmp_path_factory, monkeypatch):
    """Jev tests must not depend on or change the user's live switches."""
    if not request.node.path.name.startswith('test_jev_'):
        return
    monkeypatch.setenv('JEV_SETTINGS_FILE', str(tmp_path_factory.mktemp('jev-settings') / 'settings.json'))
    for name in ('JEV_ENABLED', 'JEV_ENTRY', 'JEV_PRINT_JUDGMENTS'):
        monkeypatch.delenv(name, raising=False)
