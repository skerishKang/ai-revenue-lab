"""Filter package/deploy stdout before it becomes a workflow log."""
import argparse
import json
import sys
import tomllib
from pathlib import Path


def redact(line, variables):
    # Named binding display rows are omitted entirely. Other messages are
    # filtered for both literal and JSON-escaped forms, including multiline values.
    if any(name in line for name in variables):
        return "B62_DEPLOY_VARIABLE_DISPLAY=OMITTED\n"
    forms = {form for value in variables.values() if isinstance(value, str) and value
             for form in (value, json.dumps(value)[1:-1]) if form}
    for value in sorted(forms, key=len, reverse=True):
        line = line.replace(value, "[REDACTED]")
    return line


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    variables = tomllib.loads(args.config.read_text()).get("vars", {})
    for line in sys.stdin:
        sys.stdout.write(redact(line, variables))
