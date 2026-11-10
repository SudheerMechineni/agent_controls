import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


class ContractTest(unittest.TestCase):
    def load(self, path):
        return json.loads((ROOT / path).read_text())

    def test_action_examples_conform(self):
        schema = self.load("contracts/action.schema.json")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        validator.validate(self.load("examples/action.json"))

    def test_action_schema_rejects_identity_injection(self):
        action = self.load("examples/action.json")
        action["approved"] = True
        validator = Draft202012Validator(self.load("contracts/action.schema.json"))
        self.assertFalse(validator.is_valid(action))

    def test_event_example_conforms_and_forbids_raw_token(self):
        schema = self.load("contracts/authority-event.schema.json")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        event = self.load("examples/authority-event.json")
        validator.validate(event)
        altered = copy.deepcopy(event)
        altered["data"]["access_token"] = "synthetic-secret"
        self.assertFalse(validator.is_valid(altered))

    def test_generated_openapi_has_defined_action_and_security(self):
        spec = self.load("contracts/authority.openapi.json")
        self.assertIn("Action", spec["components"]["schemas"])
        self.assertIn("HTTPBearer", spec["components"]["securitySchemes"])
        self.assertIn("/v1/actions/execute", spec["paths"])


if __name__ == "__main__":
    unittest.main()
