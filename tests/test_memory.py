from datetime import date, datetime
from types import SimpleNamespace

from poyi import cli
from poyi.brain.agent import Brain
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import Poyi
from poyi.memory import MemoryStore, PoyiMemoryTool, decay_profile, render_memory_context
from poyi.memory.consolidate import Consolidation, consolidate
from tests.fakes import FakeClient, simple_turn

TODAY = date(2026, 9, 7)


def make_store(tmp_path):
    return MemoryStore(tmp_path / "memory", today=lambda: TODAY).ensure()


# --- store ---------------------------------------------------------------------

def test_ensure_creates_templates(tmp_path):
    store = make_store(tmp_path)
    assert "# Profile" in store.profile()
    assert "## Promised" in store.threads()
    assert {rel for rel, _ in store.files()} == {"profile.md", "threads.md"}


def test_append_log_creates_a_dated_file(tmp_path):
    store = make_store(tmp_path)
    store.append_log("Abdul said he's tired", when=datetime(2026, 9, 7, 21, 5))
    store.append_log("second thing", when=datetime(2026, 9, 7, 21, 6))
    text = store.read_log(TODAY)
    assert text.startswith("# 2026-09-07\n\n- 21:05 Abdul said he's tired\n- 21:06 second thing\n")


def test_render_for_prompt_has_sections_and_today(tmp_path):
    store = make_store(tmp_path)
    store.append_log("hello", when=datetime(2026, 9, 7, 9, 0))
    store.write_tomorrow_note("Ask about the dentist.")
    text = render_memory_context(store)
    assert text.startswith("# What you remember")
    for heading in ("## Profile", "## Threads", "## Note from the last nightly pass", "## Today so far"):
        assert heading in text
    assert "Ask about the dentist." in text


def test_render_falls_back_to_most_recent_day(tmp_path):
    store = make_store(tmp_path)
    store.append_log("yesterday's thing", when=datetime(2026, 9, 6, 9, 0))
    text = store.render_for_prompt()
    assert "## Most recent day (2026-09-06)" in text and "yesterday's thing" in text


def test_render_truncates(tmp_path):
    store = make_store(tmp_path)
    store.write_profile("x" * 5000, backup=False)
    assert store.render_for_prompt(max_chars=1000).endswith("[memory truncated for length]")


def test_decay_drops_old_untagged_keeps_kept():
    text = "# Profile\n- old fact (seen: 2026-01-01)\n- fresh fact (seen: 2026-09-01)\n- eternal (seen: 2020-01-01) (keep)\n- untagged line\n"
    kept, dropped = decay_profile(text, TODAY, days=60)
    assert dropped == ["- old fact (seen: 2026-01-01)"]
    assert "fresh fact" in kept and "eternal" in kept and "untagged line" in kept and "# Profile" in kept


def test_write_profile_backs_up(tmp_path):
    store = make_store(tmp_path)
    store.write_profile("# Profile\n- new (seen: 2026-09-07)")
    backups = list(store.history_dir.glob("profile-*.md"))
    assert len(backups) == 1 and "# Profile" in backups[0].read_text()


def test_wipe(tmp_path):
    store = make_store(tmp_path)
    store.append_log("x")
    store.wipe()
    assert {rel for rel, _ in store.files()} == {"profile.md", "threads.md"}


# --- tool --------------------------------------------------------------------------

def test_tool_view_directory_and_file(tmp_path):
    tool = PoyiMemoryTool(make_store(tmp_path))
    listing = tool.call({"command": "view", "path": "/memories"})
    assert "Directory: /memories" in listing and "- /memories/profile.md" in listing
    body = tool.call({"command": "view", "path": "/memories/threads.md"})
    assert body.startswith("1: # Threads")
    ranged = tool.call({"command": "view", "path": "/memories/threads.md", "view_range": [3, 3]})
    assert ranged == "3: ## Promised"


def test_tool_create_replace_insert_delete_rename(tmp_path):
    tool = PoyiMemoryTool(make_store(tmp_path))
    assert tool.call({"command": "create", "path": "/memories/log/2026-09-07.md", "file_text": "# 2026-09-07\n\n- 09:00 hi\n"}).startswith("Created")
    assert tool.call({"command": "str_replace", "path": "/memories/log/2026-09-07.md", "old_str": "hi", "new_str": "hello"}).startswith("Edited")
    assert "hello" in (tmp_path / "memory/log/2026-09-07.md").read_text()
    assert tool.call({"command": "str_replace", "path": "/memories/log/2026-09-07.md", "old_str": "zzz", "new_str": "y"}).startswith("Error")
    assert tool.call({"command": "insert", "path": "/memories/log/2026-09-07.md", "insert_line": 0, "insert_text": "top"}).startswith("Inserted")
    assert (tmp_path / "memory/log/2026-09-07.md").read_text().startswith("top\n# 2026-09-07")
    assert tool.call({"command": "rename", "old_path": "/memories/log/2026-09-07.md", "new_path": "/memories/log/moved.md"}).startswith("Renamed")
    assert tool.call({"command": "delete", "path": "/memories/log/moved.md"}).startswith("Deleted")
    assert tool.call({"command": "view", "path": "/memories/log/moved.md"}).startswith("Error")


def test_tool_refuses_escapes_and_root_delete(tmp_path):
    tool = PoyiMemoryTool(make_store(tmp_path))
    assert tool.call({"command": "view", "path": "/etc/passwd"}).startswith("Error")
    assert tool.call({"command": "view", "path": "/memories/../../etc/passwd"}).startswith("Error")
    assert tool.call({"command": "delete", "path": "/memories"}).startswith("Error")
    assert tool.call({"command": "create", "path": "/memories/../x.md", "file_text": "x"}).startswith("Error")
    assert not (tmp_path / "x.md").exists()


def test_tool_clear_all(tmp_path):
    store = make_store(tmp_path)
    store.append_log("x")
    tool = PoyiMemoryTool(store)
    assert tool.clear_all_memory() == "All memory cleared."
    assert not list(store.log_dir.glob("*.md"))


def test_tool_declares_itself_as_the_memory_tool(tmp_path):
    assert PoyiMemoryTool(make_store(tmp_path)).to_dict() == {"type": "memory_20250818", "name": "memory"}


# --- consolidation -------------------------------------------------------------------

class FakeParseClient:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **params):
        self.calls.append(params)
        return SimpleNamespace(parsed_output=self.result)


def test_consolidate_writes_and_decays(tmp_path):
    store = make_store(tmp_path)
    store.append_log("Abdul mentioned his sister Amina", when=datetime(2026, 9, 7, 20, 0))
    result = Consolidation(
        profile="# Profile\n\n## People who matter\n- sister Amina (seen: 2026-09-07)\n- old colleague (seen: 2026-01-01)\n",
        threads="# Threads\n\n## Promised\n- reply to Sam\n",
        tomorrow="Ask how Amina is.",
        dropped=["removed a duplicate line"],
    )
    client = FakeParseClient(result)
    out = consolidate(store, Settings(), client=client, today=TODAY)
    sent = client.calls[0]
    assert sent["model"] == "claude-opus-5" and sent["output_format"] is Consolidation
    assert "2026-09-07" in sent["system"] and "Abdul mentioned his sister Amina" in sent["messages"][0]["content"]
    assert "sister Amina" in store.profile() and "old colleague" not in store.profile()
    assert out.dropped == ["removed a duplicate line", "decayed: - old colleague (seen: 2026-01-01)"]
    assert store.threads().startswith("# Threads") and store.tomorrow_note().strip() == "Ask how Amina is."
    assert "nightly pass ran" in store.read_log(TODAY)
    assert list(store.history_dir.glob("profile-*.md"))


def test_consolidate_dry_run_writes_nothing(tmp_path):
    store = make_store(tmp_path)
    before = store.profile()
    result = Consolidation(profile="# Profile\n- x (seen: 2026-09-07)\n", threads="# Threads\n", tomorrow="", dropped=[])
    consolidate(store, Settings(), client=FakeParseClient(result), today=TODAY, dry_run=True)
    assert store.profile() == before and store.tomorrow_note() == ""


# --- wiring ------------------------------------------------------------------------------

def test_brain_sends_context_as_second_cached_block():
    client = FakeClient([simple_turn("ok")])
    brain = Brain(Settings(), client=client, tools=[], context="# What you remember\n\nstuff")
    brain.reply("hi")
    blocks = client.calls[0]["system"]
    assert len(blocks) == 2 and blocks[1]["text"].startswith("# What you remember")
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)


def test_system_prompt_memory_section_is_opt_in():
    assert "/memories/profile.md" not in build_system_prompt(Settings())
    assert "/memories/profile.md" in build_system_prompt(Settings(), memory=True)


def test_default_assembles_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: True)
    being = Poyi.default(Settings(home=tmp_path))
    assert being.memory is not None and being.memory.root == tmp_path / "memory"
    assert being.brain is not None
    assert "What you remember" in being.brain.context
    assert "/memories/profile.md" in being.brain.system
    assert any(getattr(t, "name", "") == "memory" for t in being.brain.tools)


def test_default_without_credentials_still_has_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("poyi.core.has_credentials", lambda: False)
    being = Poyi.default(Settings(home=tmp_path))
    assert being.brain is None and being.memory is not None


# --- cli ------------------------------------------------------------------------------------

def test_memory_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    assert cli.main(["memory"]) == 0
    out = capsys.readouterr().out
    assert "profile.md" in out and "threads.md" in out
    assert cli.main(["memory", "show", "threads"]) == 0
    assert "## Promised" in capsys.readouterr().out
    assert cli.main(["memory", "show", "nope.md"]) == 1
    capsys.readouterr()
    (tmp_path / "memory" / "log").mkdir(exist_ok=True)
    (tmp_path / "memory" / "log" / "2026-09-07.md").write_text("x")
    assert cli.main(["memory", "forget", "log/2026-09-07.md"]) == 0
    assert not (tmp_path / "memory" / "log" / "2026-09-07.md").exists()
    assert cli.main(["memory", "forget", "--all", "--yes"]) == 0
    assert "All memory cleared." in capsys.readouterr().out


def test_consolidate_cli_needs_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.cli.has_credentials", lambda: False)
    assert cli.main(["consolidate"]) == 1
    assert "MISSING" in capsys.readouterr().out


def test_consolidate_cli_prints_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POYI_HOME", str(tmp_path))
    monkeypatch.setattr("poyi.cli.has_credentials", lambda: True)
    result = Consolidation(profile="# Profile\n- a (seen: 2026-09-07)", threads="# Threads", tomorrow="Say hi.", dropped=["gone"])
    monkeypatch.setattr("poyi.cli.consolidate", lambda store, settings, dry_run: result)
    assert cli.main(["consolidate", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Say hi." in out and "- gone" in out and "dry run" in out


def test_tool_insert_creates_a_missing_log_with_a_header(tmp_path):
    tool = PoyiMemoryTool(make_store(tmp_path))
    out = tool.call({"command": "insert", "path": "/memories/log/2026-09-08.md", "insert_line": 5, "insert_text": "- 09:00 first thing"})
    assert out.startswith("Inserted 1 line(s)")
    assert (tmp_path / "memory/log/2026-09-08.md").read_text() == "# 2026-09-08\n\n- 09:00 first thing\n"
    out = tool.call({"command": "insert", "path": "/memories/notes/scratch.md", "insert_line": 0, "insert_text": "top"})
    assert out.startswith("Inserted") and (tmp_path / "memory/notes/scratch.md").read_text() == "top\n"
