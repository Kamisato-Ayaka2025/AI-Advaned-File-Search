from __future__ import annotations

from aimem.everything import EverythingClient


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_parse_everything_json(monkeypatch):
    payload = {
        "totalResults": 2,
        "results": [
            {
                "type": "file",
                "name": "报价单.xlsx",
                "path": "C:\\Users\\me\\Documents\\",
                "size": "2048",
                "date_modified": "2025-10-12T15:30:00",
            },
            {
                "type": "folder",
                "name": "Documents",
                "path": "C:\\Users\\me\\",
            },
        ],
    }
    monkeypatch.setattr(
        "aimem.everything.requests.get", lambda *a, **k: _Resp(payload)
    )
    client = EverythingClient()
    rows = client.search("报价单")
    assert len(rows) == 1
    assert rows[0].path == "C:\\Users\\me\\Documents\\报价单.xlsx"
    assert rows[0].size == 2048
    assert rows[0].ext == "xlsx"
    assert rows[0].mtime is not None


def test_probe_ok(monkeypatch):
    monkeypatch.setattr(
        "aimem.everything.requests.get", lambda *a, **k: _Resp({"results": []})
    )
    ok, msg = EverythingClient().probe()
    assert ok and msg == "ok"
