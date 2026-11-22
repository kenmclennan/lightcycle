from dataclasses import dataclass
from typing import Optional, Tuple

import lightcycle.frontmatter as frontmatter
import lightcycle.config_edit as config_edit
from lightcycle.application.errors import UseCaseError
from lightcycle.config_callouts import callout_problems
from lightcycle.config_schema import (
    BLOCK,
    CALLOUT,
    CASEFOLDED_LISTS,
    KEY_KINDS,
    LIST,
    NO_USABLE_DEFAULT,
    SEED,
    ConfigAddressError,
    block_key_value,
    list_token,
    normalize_seed_value,
    resolve_address,
)


class ConfigEditError(UseCaseError):
    pass


@dataclass(frozen=True)
class ConfigGetResult:
    lines: Tuple[str, ...]
    note: Optional[str] = None


@dataclass(frozen=True)
class ConfigEditResult:
    message: str
    changed: bool
    callout_changed: bool = False
    warnings: Tuple[str, ...] = ()


class ConfigEditUseCase:
    def __init__(self, config):
        self._config = config

    def _address(self, key, values):
        blocks = {k for k, v in values.items() if isinstance(v, dict)}
        try:
            return resolve_address(key, blocks)
        except ConfigAddressError as e:
            raise ConfigEditError(str(e))

    def get(self, key):
        values = self._config.load_config()
        address = self._address(key, values)
        if address.kind == SEED:
            return self._get_seed(key)
        if address.kind == BLOCK:
            block = values.get(key)
            if isinstance(block, dict):
                return ConfigGetResult(tuple("%s: %s" % (k, v) for k, v in block.items()))
            if block is None:
                raise ConfigEditError("%s is not set" % key)
            return ConfigGetResult((str(block),))
        block = values.get(address.block)
        value = block.get(address.inner) if isinstance(block, dict) else None
        if value is None:
            raise ConfigEditError("%s is not set" % key)
        return ConfigGetResult((str(value),))

    def _get_seed(self, key):
        setting = next(s for s in self._config.resolved_settings() if s.key == key)
        if setting.state in ("invalid", "unset"):
            raise ConfigEditError("%s is not set (%s)" % (key, setting.error))
        value = setting.value
        if value is None or value == "":
            raise ConfigEditError("%s is not set" % key)
        note = None
        if setting.state == "env":
            note = "overridden by $%s in this environment" % setting.env_var
        if KEY_KINDS[key] == LIST:
            return ConfigGetResult(tuple(sorted(value)), note)
        if isinstance(value, bool):
            return ConfigGetResult(("true" if value else "false",), note)
        return ConfigGetResult((str(value),), note)

    def _load(self):
        self._config.ensure_config()
        text = self._config.read_config_text()
        return text, text.splitlines(keepends=True), frontmatter.parse_frontmatter(text)

    def set(self, key, values):
        text, lines, parsed = self._load()
        address = self._address(key, parsed)
        if address.kind == SEED:
            stored = self._seed_value(key, values)
            candidate = "".join(config_edit.set_top_level(lines, key, stored))
            return self._commit_seed(key, text, candidate, "set %s to %s" % (key, stored), stored)
        if address.kind == BLOCK:
            raise ConfigEditError("%s is a block; set a key in it as %s.<key>" % (key, key))
        self._require_block(parsed, address)
        try:
            stored = block_key_value(address.family, address.inner, values)
        except ValueError as e:
            raise ConfigEditError(str(e))
        candidate = "".join(config_edit.set_block_key(lines, address.block, address.inner, stored))
        if candidate == text:
            return ConfigEditResult("%s is already %s" % (key, stored), False)
        self._config.write_config_text(candidate)
        return ConfigEditResult(
            "set %s to %s" % (key, stored), True,
            callout_changed=address.family == CALLOUT,
            warnings=self._missing_callout_keys(address),
        )

    def unset(self, key):
        text, lines, parsed = self._load()
        address = self._address(key, parsed)
        if address.kind == SEED:
            if key in NO_USABLE_DEFAULT:
                raise ConfigEditError("%s has no usable default; set a value" % key)
            seed = self._config.seed_value(key)
            if parsed.get(key) == seed:
                return ConfigEditResult("%s is already at its seed" % key, False)
            candidate = "".join(config_edit.set_top_level(lines, key, seed))
            return self._commit_seed(key, text, candidate, "reset %s to %s" % (key, seed), seed)
        self._require_block(parsed, address)
        if address.kind == BLOCK:
            if not isinstance(parsed.get(key), dict):
                return ConfigEditResult("%s is not set" % key, False)
            candidate = "".join(config_edit.unset_block(lines, key))
        else:
            block = parsed.get(address.block)
            if not isinstance(block, dict) or address.inner not in block:
                return ConfigEditResult("%s is not set" % key, False)
            candidate = "".join(config_edit.unset_block_key(
                lines, address.block, address.inner))
        self._config.write_config_text(candidate)
        return ConfigEditResult(
            "unset %s" % key, True, callout_changed=address.family == CALLOUT)

    def add(self, key, token):
        return self._list_edit(key, token, add=True)

    def remove(self, key, token):
        return self._list_edit(key, token, add=False)

    def _list_edit(self, key, token, add):
        text, lines, parsed = self._load()
        address = self._address(key, parsed)
        if address.kind != SEED or KEY_KINDS[key] != LIST:
            raise ConfigEditError("%s is not a list" % key)
        try:
            token = list_token(key, token)
        except ValueError as e:
            raise ConfigEditError(str(e))
        fold = key in CASEFOLDED_LISTS
        stored = str(parsed.get(key) or "")
        if add:
            new = config_edit.list_with(stored, token, fold)
            if new is None:
                return ConfigEditResult("%s already has %s" % (key, token), False)
            message = "added %s to %s" % (token, key)
        else:
            new = config_edit.list_without(stored, token, fold)
            if new is None:
                return ConfigEditResult("%s does not have %s" % (key, token), False)
            if not new:
                raise ConfigEditError("would leave %s empty" % key)
            message = "removed %s from %s" % (token, key)
        candidate = "".join(config_edit.set_top_level(lines, key, new))
        return self._commit_seed(key, text, candidate, message, new)

    def _seed_value(self, key, values):
        try:
            return normalize_seed_value(key, values)
        except ValueError as e:
            raise ConfigEditError(str(e))

    def _commit_seed(self, key, text, candidate, message, stored):
        if candidate == text:
            return ConfigEditResult("%s is already %s" % (key, stored), False)
        problem = self._config.candidate_problem(candidate, key)
        if problem:
            raise ConfigEditError(problem)
        self._config.write_config_text(candidate)
        return ConfigEditResult(message, True)

    def _require_block(self, parsed, address):
        existing = parsed.get(address.block)
        if existing is not None and not isinstance(existing, dict):
            raise ConfigEditError(
                "%s is a plain value, not a block; unset it with `lc config --edit`" % address.block)

    def _missing_callout_keys(self, address):
        if address.family != CALLOUT:
            return ()
        block = self._config.load_config().get(address.block)
        callout_id = address.block[len("callout-"):]
        return tuple(
            "callout %s: %s" % (callout_id, p)
            for p in callout_problems(block or {}, callout_id) if "missing or blank" in p)
