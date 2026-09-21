import pytest

from tests.support.screen_render import (
    _launch,
    _long_description_store,
    _open_hub,
    render,
)


PARAGRAPH_START = {"goal-hub#overview": "Every project", "hub#long-description": "This item exists"}


def _paragraph(frame, start):
    rows = [row[1:-1].rstrip(" ▄▀█") for row in frame.split("\n")[1:-1]]
    first = next(i for i, row in enumerate(rows) if row.startswith(start))
    block = []
    for row in rows[first:]:
        if not row.strip("─"):
            break
        block.append(row)
    return block


@pytest.mark.parametrize("state", sorted(PARAGRAPH_START))
def test_prose_wrap_column_moves_with_terminal_width_at_mount(state):
    narrow = _paragraph(render(state, size=(100, 40)), PARAGRAPH_START[state])
    wide = _paragraph(render(state, size=(140, 40)), PARAGRAPH_START[state])

    assert max(map(len, wide)) > max(map(len, narrow))
    assert max(map(len, narrow)) <= 98
    assert max(map(len, wide)) <= 138


def test_pane_exactly_at_the_min_width_wraps_without_overflow():
    state = "hub#long-description"
    lines = _paragraph(render(state, size=(80, 40)), PARAGRAPH_START[state])

    assert max(map(len, lines)) <= 78


def test_item_hub_description_rewraps_on_resize_without_a_poll():
    store, item = _long_description_store()
    session = _open_hub(_launch(store, size=(100, 40)), item, tab="description")
    try:
        def widest():
            strips = session.run(lambda: session.app.screen._compositor.render_strips())
            frame = "\n".join(strip.text for strip in strips)
            return max(map(len, _paragraph(frame, PARAGRAPH_START["hub#long-description"])))

        before = widest()
        session.resize(140, 40)
        session.pause()
        session.pause()
        assert widest() > before
    finally:
        session.close()

