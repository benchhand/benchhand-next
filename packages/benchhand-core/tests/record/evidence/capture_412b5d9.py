# /// script
# requires-python = ">=3.12"
# dependencies = ["jsonschema>=4.23", "pyyaml>=6.0", "referencing>=0.28.4"]
# ///
"""Capture the prototype's acceptance inventory, evidence_sha256 and expected digest for the digest case
(digest_case.py), at release.toml reference_commit 412b5d9. Run from the prototype's
skills/cad-record/scripts directory of a copy of the snapshot (see test_digest.py):

    uv run --script <this file> <dir laid out by digest_case>

The record (ledger entries, dispositions and source artifacts) is the prototype's reading of the v2 tree;
the files are hashed in the v3 tree, so both services see the same bytes.
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
evidence = importlib.import_module("evidence")

target = Path(sys.argv[1])
record = evidence.mi.load_record(target / "v2" / "hw")
hw = target / "v3" / "hw"
version_sha = evidence._sha256(hw / "versions" / "v1" / "manifest.json")
packets, _ = evidence.collect_packets(hw, "v1", version_sha)
inventory = evidence.acceptance_inventory(hw, record, packets)
print(
    json.dumps(
        {
            "source": "prototype 412b5d9 evidence.acceptance_inventory and expected_digest on digest_case",
            "inventory": inventory,
            "evidence_sha256": evidence.acceptance_digest(inventory),
            "expected_sha256": evidence.expected_digest(evidence.mi.required_checks(record)),
        },
        indent=1,
        sort_keys=True,
    )
)
