from pathlib import Path

from tests.support.step_collisions import extract_steps, find_collisions, format_collisions, check_files


def test_real_suite_has_no_step_collisions():
    collisions = check_files(sorted(Path("tests/feature").glob("test_*.py")))
    assert collisions == [], format_collisions(collisions)


def test_a_generic_and_literal_collision_is_caught_loudly():
    source = """
from pytest_bdd import when, parsers


@when(parsers.parse("{key} is pressed"))
def _generic_key_pressed(key):
    pass


@when("Ctrl-D is pressed")
def _explicit_ctrl_d_pressed():
    pass
"""
    steps = extract_steps(source, label="fixture.py")
    collisions = find_collisions(steps)

    assert len(collisions) == 1
    message = format_collisions(collisions)
    assert "_generic_key_pressed" in message
    assert "_explicit_ctrl_d_pressed" in message
    assert "5" in message
    assert "10" in message


def test_same_literal_stacked_across_types_is_not_a_collision():
    source = """
from pytest_bdd import given, when


@given("the thing is set up")
@when("the thing is set up")
def _shared_step():
    pass
"""
    steps = extract_steps(source, label="fixture.py")
    assert find_collisions(steps) == []


def test_a_lone_literal_or_lone_generic_produces_nothing():
    literal_only = """
from pytest_bdd import when


@when("Ctrl-D is pressed")
def _explicit():
    pass
"""
    generic_only = """
from pytest_bdd import when, parsers


@when(parsers.parse("{key} is pressed"))
def _generic(key):
    pass
"""
    assert find_collisions(extract_steps(literal_only, label="fixture.py")) == []
    assert find_collisions(extract_steps(generic_only, label="fixture.py")) == []
