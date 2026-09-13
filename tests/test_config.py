from pathlib import Path

from poyi.config import Settings, has_credentials, load_env_file


def test_settings_from_env(tmp_path):
    env = {
        "POYI_HOME": str(tmp_path),
        "POYI_MODEL": "claude-opus-5",
        "POYI_EFFORT": "low",
        "POYI_USER": "Abdul",
        "POYI_WEB": "false",
        "POYI_FALLBACKS": "0",
    }
    s = Settings.from_env(env)
    assert s.model == "claude-opus-5" and s.effort == "low" and s.user_name == "Abdul"
    assert s.web is False and s.fallbacks is False and s.compaction is True
    assert s.home == tmp_path


def test_env_file_is_loaded_without_overriding(tmp_path):
    (tmp_path / "env").write_text("POYI_USER=Filey\nPOYI_ADDRESS='sir'\n# comment\nBAD LINE\n")
    env = {"POYI_HOME": str(tmp_path), "POYI_USER": "FromEnv"}
    s = Settings.from_env(env)
    assert s.user_name == "FromEnv"
    assert s.address == "sir"


def test_load_env_file_missing_is_fine(tmp_path):
    env: dict[str, str] = {}
    load_env_file(tmp_path / "nope", env)
    assert env == {}


def test_has_credentials(tmp_path):
    assert has_credentials({"ANTHROPIC_API_KEY": "sk-test"})
    assert has_credentials({"ANTHROPIC_AUTH_TOKEN": "tok"})
    assert not has_credentials({"XDG_CONFIG_HOME": str(tmp_path)})
    (tmp_path / "anthropic").mkdir()
    assert not has_credentials({"XDG_CONFIG_HOME": str(tmp_path)})
    (tmp_path / "anthropic" / "profile").write_text("x")
    assert has_credentials({"XDG_CONFIG_HOME": str(tmp_path)})
