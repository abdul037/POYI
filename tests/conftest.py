import pytest


@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch):
    """Never shell out to osascript, pmset, etc. from the suite.

    Tests that want the real `run` import it by name before this runs; tests
    that want a specific fake pass a `runner=`.
    """
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    monkeypatch.setattr("poyi.initiative.watchers.run", lambda argv, timeout=3.0: "")
