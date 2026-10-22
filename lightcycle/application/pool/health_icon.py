from dataclasses import dataclass
from typing import Optional

from lightcycle.config import ConfigError
from lightcycle.domain.pool import (
    HEALTH_IMAGE_IDS, claude_health_score, github_health_score, health_image_state, health_score,
    icon_columns, placeholder_rows, png_size, pool_health_score, upgrade_config_health_score,
)


@dataclass(frozen=True)
class HealthIconReading:
    state: str
    image_id: int
    columns: int
    rows: tuple
    rgb: tuple


class HealthIconUseCase:
    def __init__(self, fs, config, health_icon):
        self._fs = fs
        self._config = config
        self._health_icon = health_icon
        self._columns = {}

    def reading(self, *, pool_state, tick_health, poll_seconds, breaker_is_open, github,
                upgrade_available, config_changed, busy) -> Optional[HealthIconReading]:
        try:
            if not self._config.tui_health_icons():
                return None
            score = health_score(
                pool_health_score(
                    pool_state,
                    tick_health.level if tick_health is not None else None,
                    tick_health.median_seconds if tick_health is not None else None,
                    poll_seconds,
                ),
                claude_health_score(breaker_is_open),
                github_health_score(
                    github.remaining if github is not None and github.known else None,
                    github.limit if github is not None and github.known else None,
                ),
                upgrade_config_health_score(upgrade_available, config_changed),
            )
            state = health_image_state(score, busy)
            path = self._config.tui_health_icon_path(state)
        except ConfigError:
            return None
        image_id = HEALTH_IMAGE_IDS[state]
        if state not in self._columns:
            columns = self._load(image_id, path)
            if columns is None:
                return None
            self._columns[state] = columns
        rgb, rows = placeholder_rows(image_id, self._columns[state])
        return HealthIconReading(state, image_id, self._columns[state], rows, rgb)

    def _load(self, image_id, path):
        if not self._fs.exists(path):
            return None
        try:
            png = self._fs.read_bytes(path)
        except OSError:
            return None
        size = png_size(png)
        if size is None:
            return None
        columns = icon_columns(*size)
        self._health_icon.transmit(image_id, png, columns)
        return columns

    def release(self):
        self._health_icon.delete_all()
        self._columns = {}
