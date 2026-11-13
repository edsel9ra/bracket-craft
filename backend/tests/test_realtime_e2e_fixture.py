import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main
from app.core import config


@pytest.mark.parametrize('environment', ['production', 'prod', 'staging', 'test'])
def test_e2e_fixture_refuses_non_development_before_installing_adapters(monkeypatch, environment):
    previous = main.private_delivery.authorizer
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(app_env=environment))
    with pytest.raises(RuntimeError, match='fuera de desarrollo'):
        runpy.run_path(str(Path(__file__).with_name('realtime_e2e_server.py')))
    assert main.private_delivery.authorizer is previous
