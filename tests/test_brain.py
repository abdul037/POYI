from types import SimpleNamespace

from poyi.brain.agent import REFUSAL_LINE, Brain, Event
from poyi.brain.character import build_system_prompt
from poyi.config import Settings
from poyi.core import NO_MIND, Poyi
from poyi.identity import FULL_FORM, NAME
from tests.fakes import FakeClient, FakeStream, final_message, simple_turn, text_delta, thinking_delta, tool_start


def make_brain(turns, **settings):
    client = FakeClient(turns)
    return Brain(Settings(**settings), client=client, tools=[]), client


def test_stream_yields_text_and_done():
    brain, _ = make_brain([simple_turn("Hello there.")])
    events = list(brain.stream("hi"))
    assert "".join(e.data for e in events if e.kind == "text") == "Hello there."
    assert events[-1] == Event("done")


def test_reply_joins_text_and_mirrors_history():
    brain, client = make_brain([simple_turn("Canberra.")])
    assert brain.reply("capital of australia?") == "Canberra."
    assert brain.messages[0] == {"role": "user", "content": "capital of australia?"}
    assert brain.messages[1]["role"] == "assistant"
    assert brain.messages[1]["content"][0].text == "Canberra."
    assert brain.last_usage.output_tokens == 5


def test_history_is_sent_on_the_next_turn_as_a_copy():
    brain, client = make_brain([simple_turn("one")])
    brain.reply("first")
    client.turns = [simple_turn("two")]
    brain.reply("second")
    sent = client.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent is not brain.messages


def test_tool_turns_are_mirrored_with_their_results():
    tool_use = SimpleNamespace(type="tool_use", id="t1", name="calculate", input={"expression": "2+2"})
    first = FakeStream([tool_start("calculate")], final_message(stop_reason="tool_use", extra_blocks=[tool_use]))
    tool_result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "4"}]}
    second, _ = simple_turn("It's 4.")
    brain, _ = make_brain([(first, tool_result), (second, None)])
    events = list(brain.stream("2+2?"))
    assert Event("tool", "calculate") in events
    assert "".join(e.data for e in events if e.kind == "text") == "It's 4."
    roles = [m["role"] for m in brain.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert brain.messages[2] is tool_result


def test_server_tool_start_is_reported_and_thinking_is_ignored():
    stream = FakeStream(
        [thinking_delta("hmm"), tool_start("web_search", server=True), text_delta("Found it.")],
        final_message("Found it."),
    )
    brain, _ = make_brain([(stream, None)])
    events = list(brain.stream("look this up"))
    assert Event("tool", "web_search") in events
    assert "".join(e.data for e in events if e.kind == "text") == "Found it."


def test_refusal_produces_a_refusal_event():
    brain, _ = make_brain([simple_turn("", stop_reason="refusal")])
    events = list(brain.stream("something bad"))
    assert Event("refusal", REFUSAL_LINE) in events


def test_request_params_keep_the_stable_prefix_cached():
    brain, client = make_brain([simple_turn("ok")], effort="low", compaction=True, fallbacks=True)
    brain.reply("hi")
    params = client.calls[0]
    assert params["model"] == "claude-opus-5"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == build_system_prompt(brain.settings)
    assert params["stream"] is True
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "low"}
    assert "compact-2026-01-12" in params["betas"]
    assert params["context_management"] == {"edits": [{"type": "compact_20260112"}]}
    assert params["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in params["betas"]


def test_request_params_can_drop_betas():
    brain, client = make_brain([simple_turn("ok")], compaction=False, fallbacks=False)
    brain.reply("hi")
    params = client.calls[0]
    assert "betas" not in params and "fallbacks" not in params and "context_management" not in params


def test_system_prompt_is_stable_and_names_the_character():
    prompt = build_system_prompt(Settings(user_name="Abdul", address="sir"))
    assert NAME in prompt and FULL_FORM in prompt
    assert "not human" in prompt
    assert "called Abdul" in prompt and '"sir"' in prompt
    assert prompt == build_system_prompt(Settings(user_name="Abdul", address="sir"))
    plain = build_system_prompt(Settings())
    assert "About them" not in plain


def test_poyi_without_a_brain_is_honest_about_it():
    being = Poyi()
    assert not being.awake
    assert being.reply("hello") == NO_MIND
    assert being.history == [("user", "hello"), (NAME.lower(), NO_MIND)]


def test_poyi_with_a_brain_records_the_reply():
    brain, _ = make_brain([simple_turn("Hello, Abdul.")])
    being = Poyi(brain=brain)
    assert being.awake
    assert being.reply("hi") == "Hello, Abdul."
    assert being.history[-1] == (NAME.lower(), "Hello, Abdul.")


def test_poyi_refusal_becomes_the_refusal_line():
    brain, _ = make_brain([simple_turn("", stop_reason="refusal")])
    assert Poyi(brain=brain).reply("no") == REFUSAL_LINE
