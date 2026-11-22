import json
import os
import unittest

from lightcycle.domain.work import callout_response as cr
from lightcycle.domain.work.callout_response import (
    CalloutResponse,
    CalloutUsage,
    PreflightResponse,
    validate_callout_response,
    validate_preflight_response,
)

SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "schemas")
SCHEMA = os.path.join(SCHEMAS, "callout-response.schema.json")
PREFLIGHT_SCHEMA = os.path.join(SCHEMAS, "callout-preflight.schema.json")


def art(**kw):
    base = {"label": "L", "kind": "text", "value": "v"}
    base.update(kw)
    return base


def check(**body):
    payload = {"status": "ok", "message": "", "artifacts": []}
    payload.update(body)
    return validate_callout_response(json.dumps(payload))


class TestValidate(unittest.TestCase):
    def test_a_valid_ok_response_is_parsed(self):
        parsed = check(artifacts=[art(kind="link", value="myapp://open?x=1")])
        self.assertIsInstance(parsed, CalloutResponse)
        self.assertEqual(parsed.artifacts[0].value, "myapp://open?x=1")

    def test_failed_with_a_message_is_valid_and_without_one_is_rejected(self):
        self.assertIsInstance(check(status="failed", message="why"), CalloutResponse)
        self.assertIsInstance(check(status="failed", message=""), str)

    def test_each_malformed_response_is_rejected_with_a_string(self):
        cases = [
            check(status="maybe"),
            check(artifacts=[art(kind="video")]),
            check(artifacts=[art()] * 21),
            check(artifacts=[art(value="x" * 65537)]),
            check(artifacts=[art(label="")]),
            validate_callout_response("not json"),
            validate_callout_response("[]"),
            check(artifacts=[art(kind="link", value="has space://x")]),
            check(artifacts=[art(kind="link", value="no-scheme")]),
        ]
        for case in cases:
            self.assertIsInstance(case, str)

    def test_exactly_the_limits_are_accepted(self):
        self.assertIsInstance(check(artifacts=[art()] * 20), CalloutResponse)
        self.assertIsInstance(check(artifacts=[art(value="x" * 65536)]), CalloutResponse)

    def test_schema_file_matches_validator(self):
        with open(SCHEMA) as f:
            schema = json.load(f)
        item = schema["properties"]["artifacts"]["items"]
        self.assertEqual(tuple(schema["properties"]["status"]["enum"]), cr.STATUSES)
        self.assertEqual(tuple(item["properties"]["kind"]["enum"]), cr.KINDS)
        self.assertEqual(schema["properties"]["artifacts"]["maxItems"], cr.MAX_ARTIFACTS)
        self.assertEqual(item["properties"]["value"]["maxLength"], cr.MAX_VALUE_CHARS)
        self.assertEqual(item["properties"]["label"]["maxLength"], cr.MAX_LABEL_CHARS)
        self.assertEqual(schema["required"], ["status"])
        self.assertEqual(sorted(item["required"]), ["kind", "label", "value"])
        self.assertEqual(schema["then"]["anyOf"][0]["required"], ["message"])
        self.assertEqual(
            schema["then"]["anyOf"][1]["required"], ["errors"])
        error = schema["properties"]["errors"]["items"]
        self.assertEqual(schema["properties"]["errors"]["maxItems"], cr.MAX_ERRORS)
        self.assertEqual(error["properties"]["message"]["maxLength"], cr.MAX_ERROR_CHARS)
        self.assertEqual(error["properties"]["fix"]["maxLength"], cr.MAX_ERROR_CHARS)
        self.assertEqual(sorted(error["required"]), ["fix", "message"])
        usage = schema["properties"]["usage"]
        self.assertEqual(usage["required"], ["cost_usd"])
        self.assertEqual(usage["properties"]["cost_usd"]["minimum"], 0)
        self.assertEqual(usage["properties"]["cost_usd"]["maximum"], cr.MAX_USAGE_COST_USD)
        self.assertEqual(usage["properties"]["model"]["maxLength"], cr.MAX_LABEL_CHARS)
        self.assertEqual(cr.PROTOCOL, 2)
        self.assertIn("protocol 2", schema["title"])

        with open(PREFLIGHT_SCHEMA) as f:
            preflight = json.load(f)
        error = preflight["properties"]["errors"]["items"]
        self.assertEqual(tuple(preflight["properties"]["status"]["enum"]), cr.STATUSES)
        self.assertEqual(preflight["properties"]["errors"]["maxItems"], cr.MAX_ERRORS)
        self.assertEqual(error["properties"]["message"]["maxLength"], cr.MAX_ERROR_CHARS)
        self.assertEqual(error["properties"]["fix"]["maxLength"], cr.MAX_ERROR_CHARS)
        self.assertEqual(sorted(error["required"]), ["fix", "message"])
        self.assertEqual(preflight["required"], ["status"])
        self.assertEqual(preflight["then"]["required"], ["errors"])


class TestUsage(unittest.TestCase):
    def test_usage_is_parsed(self):
        parsed = check(usage={"cost_usd": 0.42, "model": "m"})
        self.assertEqual(parsed.usage, CalloutUsage(cost_usd=0.42, model="m"))

    def test_usage_absent_is_none(self):
        self.assertIsNone(check().usage)

    def test_model_is_optional(self):
        self.assertEqual(check(usage={"cost_usd": 1}).usage, CalloutUsage(cost_usd=1, model=None))

    def test_unknown_usage_keys_are_ignored(self):
        self.assertIsInstance(check(usage={"cost_usd": 1, "x": 2}), CalloutResponse)

    def test_the_bounds_are_accepted(self):
        self.assertIsInstance(check(usage={"cost_usd": 0}), CalloutResponse)
        self.assertIsInstance(check(usage={"cost_usd": 1000000}), CalloutResponse)
        self.assertIsInstance(check(usage={"cost_usd": 1, "model": "m" * 80}), CalloutResponse)

    def test_each_malformed_usage_is_rejected_naming_usage(self):
        bad = [
            {}, {"cost_usd": "1"}, {"cost_usd": True}, {"cost_usd": -1},
            {"cost_usd": 1000000.01}, {"cost_usd": 1, "model": ""},
            {"cost_usd": 1, "model": "m" * 81}, {"cost_usd": 1, "model": 3}, [], "x", None,
        ]
        for usage in bad:
            with self.subTest(usage=usage):
                problem = check(usage=usage)
                self.assertIsInstance(problem, str)
                self.assertIn("usage", problem)

    def test_nan_and_infinity_are_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                text = '{"status": "ok", "usage": {"cost_usd": %s}}' % token
                problem = validate_callout_response(text)
                self.assertIsInstance(problem, str)
                self.assertIn("usage", problem)

    def test_a_preflight_response_ignores_usage(self):
        parsed = validate_preflight_response('{"status": "ok", "usage": {"cost_usd": "x"}}')
        self.assertIsInstance(parsed, PreflightResponse)


def err(**kw):
    base = {"message": "m", "fix": "f"}
    base.update(kw)
    return base


class TestErrors(unittest.TestCase):
    def test_failed_with_only_errors_is_accepted(self):
        parsed = check(status="failed", message="", errors=[err()])
        self.assertIsInstance(parsed, CalloutResponse)
        self.assertEqual(parsed.errors[0].fix, "f")

    def test_failed_with_message_and_errors_keeps_both(self):
        parsed = check(status="failed", message="why", errors=[err()])
        self.assertEqual((parsed.message, len(parsed.errors)), ("why", 1))

    def test_failed_with_neither_message_nor_errors_is_rejected(self):
        self.assertEqual(
            check(status="failed", message="", errors=[]), "message is required when status is failed")

    def test_ok_with_errors_is_rejected(self):
        self.assertIsInstance(check(status="ok", errors=[err()]), str)

    def test_each_malformed_error_is_rejected(self):
        cases = [
            check(status="failed", errors=[{"message": "m"}]),
            check(status="failed", errors=[err(message="")]),
            check(status="failed", errors=[err()] * 21),
            check(status="failed", errors=[err(fix="x" * 501)]),
            check(status="failed", errors=[err(message="x" * 501)]),
            check(status="failed", errors="nope"),
            check(status="failed", errors=["nope"]),
        ]
        for case in cases:
            self.assertIsInstance(case, str)

    def test_exactly_the_error_limits_are_accepted(self):
        self.assertIsInstance(check(status="failed", errors=[err()] * 20), CalloutResponse)
        self.assertIsInstance(
            check(status="failed", errors=[err(fix="x" * 500, message="y" * 500)]), CalloutResponse)


def preflight(**body):
    payload = {"status": "ok"}
    payload.update(body)
    return validate_preflight_response(json.dumps(payload))


class TestPreflight(unittest.TestCase):
    def test_ok_with_no_errors_is_accepted(self):
        self.assertEqual(preflight(), PreflightResponse(status="ok"))

    def test_ok_carrying_a_protocol_one_run_response_is_accepted(self):
        self.assertIsInstance(preflight(message="", artifacts=[art()]), PreflightResponse)

    def test_failed_needs_errors(self):
        self.assertIsInstance(preflight(status="failed"), str)
        self.assertIsInstance(preflight(status="failed", errors=[]), str)
        self.assertIsInstance(preflight(status="failed", errors=[err()]), PreflightResponse)

    def test_ok_with_errors_is_rejected(self):
        self.assertIsInstance(preflight(errors=[err()]), str)

    def test_malformed_input_is_rejected(self):
        self.assertIsInstance(validate_preflight_response("nope"), str)
        self.assertIsInstance(validate_preflight_response("[]"), str)
        self.assertIsInstance(preflight(status="maybe"), str)
        self.assertIsInstance(preflight(status="failed", errors=[err(fix="")]), str)
