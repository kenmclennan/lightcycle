def block_rows(app, prefix):
    block = app.query_one("#%s-filter-block" % prefix)
    region = block.region
    strips = app.screen_stack[0]._compositor.render_strips()
    rows = []
    for y in range(region.y, region.y + region.height):
        text = "".join(segment.text for segment in strips[y].crop(region.x, region.x + region.width))
        rows.append(text)
    return rows


def block_text(app, prefix):
    return "\n".join(block_rows(app, prefix))


def last_text_row(app, prefix):
    rows = [row for row in block_rows(app, prefix) if any(ch.isalnum() for ch in row)]
    return rows[-1]
