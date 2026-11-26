"""Write a cel-go env YAML as the JSON environment the cel-expr CLI reads.

cel-expr takes only JSON, and each variable has a `type` string (`list<string>`, a message name) where cel-go
has `type_name` and `params`. Only plain variables are converted; a parameterised type would need the
grammar in cel-expr's type_grammar_ebnf.txt.

Usage: python env_json.py <scope.env.yaml> <out.json>
"""

import json
import sys

import yaml

src, out = sys.argv[1], sys.argv[2]
config = yaml.safe_load(open(src))
for v in config.get("variables", []):
    if v.get("params"):
        sys.exit(f"{v['name']}: parameterised types aren't converted")
    v["type"] = v.pop("type_name")
with open(out, "w") as fh:
    json.dump(config, fh, indent=1)
