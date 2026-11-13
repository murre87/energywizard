"""update_check.py: säg till när en nyare EnergyWizard finns, och påstå aldrig "senaste" utan att veta."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import update_check as uc  # noqa: E402


class R:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def reset():
    uc._state.update(at=0.0, result=None, busy=False)


def test_tillagg_via_supervisor(monkeypatch):
    reset()
    import requests
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    monkeypatch.setattr(requests, "get", lambda *a, **k: R({"data": {"version": "1.2.60", "version_latest": "1.2.69",
                                                                    "update_available": True}}))
    s = uc.status(block=True)
    assert s["kind"] == "addon" and s["outdated"] and s["latest"] == "1.2.69"


def test_docker_via_bildbygget(monkeypatch):
    reset()
    import requests
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setenv("APP_VERSION", "1.281")
    monkeypatch.setattr(requests, "get", lambda *a, **k: R({"workflow_runs": [{"run_number": 340}]}))
    s = uc.status(block=True)
    assert s["kind"] == "docker" and s["outdated"] and s["latest"] == "1.340"


def test_okand_version_paststar_inget(monkeypatch):
    reset()
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setenv("APP_VERSION", "dev")
    s = uc.status(block=True)
    assert s["outdated"] is False and s["latest"] is None


def test_natet_nere_behaller_forra(monkeypatch):
    reset()
    import requests
    uc._state["result"] = {"outdated": True, "latest": "1.2.69"}

    def boom(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    monkeypatch.setattr(requests, "get", boom)
    assert uc.status(block=True)["latest"] == "1.2.69"


def test_en_avisering_per_version(monkeypatch):
    reset()
    import ew_settings
    import notifier
    store, sent = {}, []
    monkeypatch.setattr(ew_settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(ew_settings, "update", lambda **kw: store.update(kw))
    monkeypatch.setattr(notifier, "send_emil", lambda *a, **k: sent.append(a[0]))
    monkeypatch.setattr(uc, "status", lambda block=False: {"outdated": True, "latest": "1.2.69", "running": "1.2.60", "kind": "addon"})
    uc._notified["version"] = None
    uc.notify_if_new()
    uc.notify_if_new()
    assert len(sent) == 1 and "1.2.69" in sent[0]
