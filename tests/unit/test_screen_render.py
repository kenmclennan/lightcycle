import pytest

from tests.support.screen_render import SCREENS, UNRENDERABLE, render


@pytest.mark.parametrize("state", sorted(SCREENS))
def test_every_registered_state_renders_a_full_frame(state):
    frame = render(state, size=(100, 30))
    rows = frame.split("\n")

    assert len(rows) == 30
    assert rows[0].startswith("┌") and rows[0].endswith("┐")
    assert rows[-1].startswith("└") and rows[-1].endswith("┘")
    assert any(row.strip("│ ") for row in rows[1:-1])


def test_a_state_the_codebase_cannot_render_names_the_ones_it_can():
    with pytest.raises(KeyError) as excinfo:
        render("hub#not-a-state")

    assert "hub#hierarchy" in str(excinfo.value)


def test_a_state_the_design_names_but_the_code_cannot_render_says_why():
    assert UNRENDERABLE

    for state, reason in UNRENDERABLE.items():
        assert state not in SCREENS
        assert reason.strip()

    state, reason = sorted(UNRENDERABLE.items())[0]
    with pytest.raises(KeyError) as excinfo:
        render(state)

    assert reason in str(excinfo.value)


def test_colour_carries_the_state_tokens_the_plain_frame_drops():
    plain = render("priority-list#normal")
    coloured = render("priority-list#normal", colour=True)

    assert "\x1b[38;2;" in coloured
    assert "\x1b[" not in plain


HEADER_FIELDS = ("project:", "theme:", "workflow:", "STEP:", "ROLE:", "ELAPSED:", "STATE:")


def test_the_demo_fixtures_exercise_every_header_field_the_hub_can_render():
    hub_frames = "\n".join(render(s) for s in sorted(SCREENS) if s.startswith("hub#"))
    missing = [f for f in HEADER_FIELDS if f not in hub_frames]

    assert not missing, (
        "no demo fixture populates %s, so no rendered frame can ever show it "
        "and every comparison against the design silently omits it" % missing
    )
