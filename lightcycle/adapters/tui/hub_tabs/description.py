from lightcycle.adapters.tui.design_system import COLOURS
from lightcycle.adapters.tui.prose_text import (
    prose_text,
    resolve_titles,
)
from lightcycle.application.work.item_context import ItemContextReader
from rich.text import Text
from lightcycle.adapters.tui.hub_widgets import (
    DescriptionPane,
    pane_text_width,
)


class DescriptionTabMixin:
    def _description_block(self, item):
        context = ItemContextReader(self._container.store).read(item)
        rows = []
        if context.repo:
            rows.append(("repo", context.repo))
        if context.workflow:
            rows.append(("workflow", context.workflow))
        for goal_id, title in context.goals:
            rows.append(("goal", "%s (%s)" % (title, goal_id)))
        for ref_id, title in context.resolves:
            rows.append(("resolves", "%s (%s)" % (title, ref_id) if title else "%s (not found)" % ref_id))
        if context.note:
            rows.append(("note", context.note))
        return tuple(rows)

    def refresh_description_width(self) -> None:
        self._render_description(self._description_item)

    def _render_description(self, item) -> None:
        self._description_item = item
        if item is None:
            return
        description = item.description
        block = self._description_block(item)
        titles = resolve_titles(self._container.store, description)
        self._has_description = bool(description) or bool(block)
        pane = self.query_one(DescriptionPane)
        width = pane_text_width(pane)
        if not width:
            return
        key = (description, block, tuple(sorted(titles.items())), width)
        if key == self._last_description:
            return
        self._last_description = key
        pane.clear()
        if block:
            label_width = max(len(label) for label, _value in block)
            for label, value in block:
                pane.write(
                    Text("%s  %s" % (label.ljust(label_width), value), style=COLOURS["dim"]),
                    width=width,
                )
            if description:
                pane.write(Text(""), width=width)
                pane.write(Text("─" * width, style=COLOURS["dim"]), width=width)
        if description:
            pane.write(prose_text(description, titles), width=width)
