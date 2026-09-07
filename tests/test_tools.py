import pytest

from poyi.brain.tools import WEB_FETCH, WEB_SEARCH, calculate, current_time, default_tools, safe_calculate
from poyi.config import Settings


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("2340 * 0.17", "397.8"),
        ("2 + 2", "4"),
        ("2 ^ 10", "1024"),
        ("sqrt(16)", "4"),
        ("round(pi, 3)", "3.142"),
        ("-(3 - 5)", "2"),
        ("7 // 2", "3"),
        ("max(1, 9, 4)", "9"),
    ],
)
def test_safe_calculate(expression, expected):
    assert safe_calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "open('x')", "a + 1", "(1).__class__", "2 ** 999999", "'a' * 3"],
)
def test_safe_calculate_rejects(expression):
    with pytest.raises((ValueError, SyntaxError, TypeError)):
        safe_calculate(expression)


def test_calculate_tool_reports_errors_instead_of_raising():
    assert calculate.call({"expression": "1 / 0"}).startswith("Could not evaluate")
    assert calculate.call({"expression": "2 + 2"}) == "4"


def test_current_time_tool_has_a_weekday():
    text = current_time.call({})
    assert any(day in text for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])


def test_default_tools_with_and_without_web():
    with_web = default_tools(Settings(web=True))
    assert WEB_SEARCH in with_web and WEB_FETCH in with_web
    without = default_tools(Settings(web=True), web=False)
    assert WEB_SEARCH not in without and len(without) == 2
    assert {t.name for t in without} == {"current_time", "calculate"}
