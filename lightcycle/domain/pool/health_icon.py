import struct

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ROWS = 2
CELL_ASPECT = 2.0
MAX_COLUMNS = 8
PLACEHOLDER = "\U0010EEEE"

DIACRITICS = tuple(chr(c) for c in (
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
))

HEALTH_IMAGE_STATES = ("0", "1", "2", "3", "4", "busy")
HEALTH_IMAGE_IDS = {
    state: 0x4C0001 + position for position, state in enumerate(HEALTH_IMAGE_STATES)
}


def png_size(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) < 24:
        return None
    if bytes(data[:8]) != PNG_SIGNATURE or bytes(data[12:16]) != b"IHDR":
        return None
    width, height = struct.unpack(">II", bytes(data[16:24]))
    if width <= 0 or height <= 0:
        return None
    return width, height


def icon_columns(width, height):
    raw = int(ROWS * CELL_ASPECT * width / height + 0.5)
    return max(1, min(MAX_COLUMNS, raw))


def placeholder_rows(image_id, columns):
    rgb = ((image_id >> 16) & 255, (image_id >> 8) & 255, image_id & 255)
    rows = tuple(
        "".join(PLACEHOLDER + DIACRITICS[row] + DIACRITICS[col] for col in range(columns))
        for row in range(ROWS)
    )
    return rgb, rows
