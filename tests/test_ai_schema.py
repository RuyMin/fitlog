import json
import unittest

from support import TEMP  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports

from app.services import claude_import, claude_records


def parameters(schema: dict):
    """Every (name, definition, required) property in a JSON schema, depth first."""
    if schema.get("type") == "object":
        required = set(schema.get("required", []))
        for name, value in schema.get("properties", {}).items():
            yield name, value, name in required
            yield from parameters(value)
    elif schema.get("type") == "array":
        yield from parameters(schema["items"])
    for option in schema.get("anyOf", []):
        yield from parameters(option)


class StructuredOutputLimitTests(unittest.TestCase):
    """Anthropic rejects (400) a structured-output schema with more than 16 union-typed or 24 optional parameters."""

    def test_record_schemas_fit_the_limits(self) -> None:
        for name, schema in [("records", claude_records.SCHEMA), ("excel import", claude_import.SCHEMA)]:
            with self.subTest(schema=name):
                found = list(parameters(schema))
                unions = [n for n, value, _ in found if "anyOf" in value or isinstance(value.get("type"), list)]
                optional = [n for n, _, required in found if not required]
                self.assertLessEqual(len(unions), 16, unions)
                self.assertLessEqual(len(optional), 24, optional)
                self.assertNotIn("minimum", json.dumps(schema))


if __name__ == "__main__":
    unittest.main()
