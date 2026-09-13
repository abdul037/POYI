import pytest


@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch, tmp_path):
    """Never shell out to osascript, pmset, etc. from the suite.

    Tests that want the real `run` import it by name before this runs; tests
    that want a specific fake pass a `runner=`.
    """
    monkeypatch.setattr("poyi.world.sensors.run", lambda argv, timeout=3.0: "")
    monkeypatch.setattr("poyi.initiative.watchers.run", lambda argv, timeout=3.0: "")
    # Never read the developer's project .env during tests.
    monkeypatch.setenv("POYI_SKIP_DOTENV", "1")
    # Isolate from the real ~/.poyi (state and any running daemon).
    monkeypatch.setenv("POYI_HOME", str(tmp_path / "poyi-home"))
