import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_one_query_per_cycle_and_disconnects_only_invalid_sessions(monkeypatch, failure):
    sessions = {sid: {"scope": "public", "tournament_id": sid} for sid in ["valid", "invalid", "unverified"]}
    monkeypatch.setattr(main, "connected_socket_sessions", sessions)
    disconnect = AsyncMock()
    monkeypatch.setattr(main.sio, "disconnect", disconnect)
    db = AsyncMock()
    db.__aenter__.return_value = db
    transaction = AsyncMock()
    db.begin = MagicMock(return_value=transaction)
    if failure:
        db.execute.side_effect = RuntimeError("offline")
    else:
        result = MagicMock()
        result.mappings.return_value.all.return_value = [
            {"sid": "valid", "is_valid": True}, {"sid": "invalid", "is_valid": False},
        ]
        db.execute.return_value = result
    monkeypatch.setattr(main, "SessionFactory", lambda: db)
    await main.revalidate_socket_sessions_cycle()
    db.execute.assert_awaited_once()
    payload = json.loads(db.execute.call_args.args[1]["sockets"])
    assert {item["sid"] for item in payload} == set(sessions)
    if failure:
        disconnect.assert_not_awaited()
    else:
        disconnect.assert_awaited_once_with("invalid")


@pytest.mark.asyncio
async def test_empty_cycle_does_not_query(monkeypatch):
    monkeypatch.setattr(main, "connected_socket_sessions", {})
    factory = MagicMock()
    monkeypatch.setattr(main, "SessionFactory", factory)
    await main.revalidate_socket_sessions_cycle()
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_failure_is_logged_without_session_data_and_does_not_stop_cycle(monkeypatch, caplog):
    sessions = {sid: {"scope": "public", "tournament_id": "private-fixture"} for sid in ["first", "second"]}
    monkeypatch.setattr(main, "connected_socket_sessions", sessions)
    disconnect = AsyncMock(side_effect=[RuntimeError("sensitive-provider-message"), None])
    monkeypatch.setattr(main.sio, "disconnect", disconnect)
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.mappings.return_value.all.return_value = [{"sid": sid, "is_valid": False} for sid in sessions]
    db.execute.return_value = result
    monkeypatch.setattr(main, "SessionFactory", lambda: db)
    await main.revalidate_socket_sessions_cycle()
    assert disconnect.await_count == 2
    assert "No se pudo desconectar un socket invalidado" in caplog.text
    assert "private-fixture" not in caplog.text
    assert "sensitive-provider-message" not in caplog.text
