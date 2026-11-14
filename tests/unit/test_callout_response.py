import json
import os
import unittest

from lightcycle.domain.work import callout_response as cr
from lightcycle.domain.work.callout_response import CalloutResponse, validate_callout_response

SCHEMA = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "schemas", "callout-response.schema.json")


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
        self.assertEqual(schema["then"]["required"], ["message"])
