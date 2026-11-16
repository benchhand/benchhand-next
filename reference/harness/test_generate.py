#!/usr/bin/env python3
"""Regression tests for neutral agent sources and generated harness profiles."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import yaml

CAD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAD / "harness"))
import generate  # noqa: E402
AGENT_NAMES = sorted(path.stem for path in (CAD / "agents").glob("*.md"))
CAPABILITIES = {"read", "write-scratch", "shell-uv", "web"}


class GeneratorCopyCase(unittest.TestCase):
    """Runs generate.py inside a throwaway copy of the checkout."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-harness-test-")
        self.addCleanup(temporary.cleanup)
        self.cad = Path(temporary.name) / "cad-agent"
        shutil.copytree(CAD, self.cad, copy_function=shutil.copyfile)
        self.generator = self.cad / "harness" / "generate.py"

    def run_generator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.generator), *args],
            cwd=self.cad,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def generate(self) -> None:
        result = self.run_generator()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class HarnessGeneratorTests(GeneratorCopyCase):
    def test_round_trip_check_and_drift_detection(self) -> None:
        self.generate()
        current = self.run_generator("--check")
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
        self.assertIn(f"PASS: {4 * len(AGENT_NAMES) + 1} harness files current", current.stdout)
        output = self.cad / "harness" / "codex" / "agents" / f"{AGENT_NAMES[0]}.toml"
        output.write_text(output.read_text(encoding="utf-8") + "# manual drift\n", encoding="utf-8")
        stale = self.run_generator("--check")
        self.assertEqual(stale.returncode, 1)
        self.assertIn(f"stale harness/codex/agents/{AGENT_NAMES[0]}.toml", stale.stderr)
        self.generate()
        unexpected = self.cad / "harness" / "kiro" / "agents" / "cad-retired-agent.json"
        unexpected.write_text("{}\n", encoding="utf-8")
        extra = self.run_generator("--check")
        self.assertEqual(extra.returncode, 1)
        self.assertIn("unexpected harness/kiro/agents/cad-retired-agent.json", extra.stderr)
        self.generate()
        self.assertFalse(unexpected.exists())


    def test_neutral_sources_have_only_contract_metadata(self) -> None:
        for path in sorted((self.cad / "agents").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            source = yaml.safe_load(text.split("---", 2)[1])
            self.assertEqual(set(source) - {"tier"}, {"name", "description", "capabilities", "skills"})
            self.assertIn(source.get("tier", "standard"), {"cheap", "standard", "strong"})
            self.assertEqual(source["name"], path.stem)
            self.assertIsInstance(source["capabilities"], list)
            self.assertIsInstance(source["skills"], list)
            self.assertTrue(set(source["capabilities"]) <= CAPABILITIES)
            self.assertNotRegex(text, r"(?i)\bOMP\b|skill://|xd://|\bBeads\b|autoloadSkills|@task|@reviewer|\.omp-plugin|PI_SESSION_ID")
            self.assertNotRegex(text, r"(?i)\b(?:task|eval)\s+(?:tool|agent|function)\b")


    def test_shell_agents_direct_file_inspection_to_read_tools(self) -> None:
        self.generate()
        for source in sorted((self.cad / "agents").glob("*.md")):
            metadata = yaml.safe_load(source.read_text(encoding="utf-8").split("---", 2)[1])
            if "shell-uv" not in metadata["capabilities"]:
                continue
            for harness, extension in (("claude", "md"), ("codex", "toml"), ("opencode", "md"), ("kiro", "json")):
                generated = self.cad / "harness" / harness / "agents" / f"{source.stem}.{extension}"
                with self.subTest(agent=source.stem, harness=harness):
                    self.assertIn("Inspect files with the available read/search tools", generated.read_text(encoding="utf-8"))
    def test_claude_plugin_marketplace_targets_repo_root(self) -> None:
        plugin = json.loads((self.cad / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((self.cad / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "cad-agent")
        self.assertEqual(plugin["agents"], [f"./harness/claude/agents/{name}.md" for name in AGENT_NAMES])
        self.assertEqual(marketplace["name"], "cad-agent")
        self.assertEqual(marketplace["plugins"][0]["name"], "cad-agent")
        self.assertEqual(marketplace["plugins"][0]["source"], "./")
        self.assertNotIn("omp", json.dumps(plugin).lower())
        self.assertNotIn("omp", json.dumps(marketplace).lower())

    def test_claude_fields_follow_subagent_frontmatter_schema(self) -> None:
        self.generate()
        for name in AGENT_NAMES:
            text = (self.cad / "harness/claude/agents" / f"{name}.md").read_text(encoding="utf-8")
            front = yaml.safe_load(text.split("---", 2)[1])
            self.assertEqual(front["name"], name)
            self.assertTrue(front["description"])
            self.assertIn("Read", front["tools"])
            self.assertIsInstance(front["skills"], list)
            self.assertEqual(front["model"], "inherit")

    def test_codex_toml_fields_and_policy_limits(self) -> None:
        self.generate()
        for path in sorted((self.cad / "harness/codex/agents").glob("*.toml")):
            config = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["name"], path.stem)
            self.assertTrue(config["description"])
            self.assertEqual(set(config), {"name", "description", "developer_instructions"})
            self.assertIn(".cad-work-only sandbox", config["developer_instructions"])
            sourcing = tomllib.loads((self.cad / "harness/codex/agents/cad-sourcing-researcher.toml").read_text(encoding="utf-8"))
            self.assertIn("inherit web access from the parent session", sourcing["developer_instructions"])
    def test_opencode_v2_frontmatter_has_ordered_rules_and_yaml_shape(self) -> None:
        self.generate()
        for path in sorted((self.cad / "harness/opencode/agents").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            front = yaml.safe_load(text.split("---", 2)[1])
            self.assertEqual(front["mode"], "subagent")
            self.assertIsInstance(front["permissions"], list)
            self.assertTrue(all(set(rule) == {"action", "resource", "effect"} for rule in front["permissions"]))
            self.assertIn({"action": "*", "resource": "*", "effect": "deny"}, front["permissions"])
            self.assertIn("<!-- Generated by cad-agent; do not edit. -->", text)

        writer = (self.cad / "harness/opencode/agents/cad-part-designer.md").read_text(encoding="utf-8")
        rules = yaml.safe_load(writer.split("---", 2)[1])["permissions"]
        edit_rules = [rule for rule in rules if rule["action"] == "edit"]
        shell_rules = [rule for rule in rules if rule["action"] == "shell"]
        self.assertEqual(edit_rules[-2:], [
            {"action": "edit", "resource": "*", "effect": "deny"},
            {"action": "edit", "resource": ".cad-work/**", "effect": "allow"},
        ])
        self.assertEqual(shell_rules[-2:], [
            {"action": "shell", "resource": "*", "effect": "deny"},
            {"action": "shell", "resource": "uv *", "effect": "allow"},
        ])
        self.assertEqual([rule for rule in rules if rule["action"] == "webfetch"], [{"action": "webfetch", "resource": "*", "effect": "deny"}])
        for path in sorted((self.cad / "harness/opencode/agents").glob("*.md")):
            parsed = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
            if path.stem != "cad-sourcing-researcher":
                self.assertTrue(any(rule == {"action": "websearch", "resource": "*", "effect": "deny"} for rule in parsed["permissions"]))

    def test_kiro_v3_json_uses_installed_skill_resources(self) -> None:
        self.generate()
        for path in sorted((self.cad / "harness/kiro/agents").glob("*.json")):
            config = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(config["name"], path.stem)
            self.assertTrue(config["description"])
            self.assertIn("read", config["tools"])
            self.assertIsInstance(config["permissions"]["rules"], list)
            self.assertTrue(config["resources"])
            self.assertTrue(all(resource.startswith("skill://.kiro/skills/cad-") for resource in config["resources"]))
            self.assertIn("<!-- Generated by cad-agent; do not edit. -->", config["prompt"])

        writer = json.loads((self.cad / "harness/kiro/agents/cad-part-designer.json").read_text(encoding="utf-8"))
        self.assertIn({"capability": "fs_write", "match": [".cad-work/**"], "effect": "allow"}, writer["permissions"]["rules"])
        self.assertIn({"capability": "shell", "match": ["uv *"], "effect": "allow"}, writer["permissions"]["rules"])
        reader = json.loads((self.cad / "harness/kiro/agents/cad-mech-reviewer.json").read_text(encoding="utf-8"))
        self.assertNotIn("write", reader["tools"])
        self.assertNotIn("shell", reader["tools"])

    def test_command_is_a_generated_opencode_skill_launcher(self) -> None:
        self.generate()
        command = (self.cad / "harness/opencode/commands/cad-flow.md").read_text(encoding="utf-8")
        front, body = command.split("---", 2)[1:]
        self.assertEqual(yaml.safe_load(front)["description"], "Prototype-to-CAD flow")
        self.assertIn("Read the `cad-flow` skill", body)
        self.assertIn("$ARGUMENTS", body)

    def test_rejects_unknown_capabilities_skills_and_names(self) -> None:
        source = self.cad / "agents/cad-analyst.md"
        original = source.read_text(encoding="utf-8")
        cases = (
            ("capabilities: [read, write-scratch, shell-uv]", "capabilities: [telepathy, read]", "capabilities must be distinct"),
            ("skills: [cad-motion, cad-analysis]", "skills: [cad-missing]", "skills name files CAD does not ship"),
            ("name: cad-analyst", "name: cad-renamed", "must be a cad-* kebab-case id"),
            ("capabilities: [read, write-scratch, shell-uv]", "capabilities: [read, read]", "capabilities must be distinct"),
        )
        try:
            for old, new, message in cases:
                with self.subTest(field=old):
                    source.write_text(original.replace(old, new, 1), encoding="utf-8")
                    result = self.run_generator("--check")
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(message, result.stderr)
        finally:
            source.write_text(original, encoding="utf-8")


class TierRenderingTests(unittest.TestCase):
    """Tier to model rendering, through generate.render and parse_tier_models."""

    MODELS = {
        "claude": {"cheap": "haiku"},
        "codex": {"cheap": "gpt-5-mini"},
        "opencode": {"cheap": "anthropic/claude-haiku-4-5#low"},
        "kiro": {"cheap": "claude-haiku-4.5"},
    }

    def agent(self, name: str) -> "generate.Agent":
        return next(agent for agent in generate.agents() if agent.name == name)

    def test_cad_clerk_is_the_cheap_tier_agent(self) -> None:
        self.assertEqual(self.agent("cad-clerk").tier, "cheap")
        self.assertEqual([a.name for a in generate.agents() if a.tier == "cheap"], ["cad-clerk"])

    def test_claude_renders_alias_and_keeps_inherit_without_a_mapping(self) -> None:
        mapped = generate.render(self.agent("cad-clerk"), "claude", self.MODELS)
        self.assertEqual(yaml.safe_load(mapped.split("---", 2)[1])["model"], "haiku")
        unmapped = generate.render(self.agent("cad-clerk"), "claude", {})
        self.assertEqual(yaml.safe_load(unmapped.split("---", 2)[1])["model"], "inherit")

    def test_opencode_renders_provider_model_variant_and_never_inherit(self) -> None:
        mapped = generate.render(self.agent("cad-clerk"), "opencode", self.MODELS)
        self.assertEqual(yaml.safe_load(mapped.split("---", 2)[1])["model"], "anthropic/claude-haiku-4-5#low")
        for agent in generate.agents():
            for models in ({}, self.MODELS):
                text = generate.render(agent, "opencode", models)
                with self.subTest(agent=agent.name, mapped=bool(models)):
                    self.assertNotIn("inherit", text.split("---", 2)[1])
        bare = generate.render(self.agent("cad-clerk"), "opencode", {})
        self.assertNotIn("model", yaml.safe_load(bare.split("---", 2)[1]))

    def test_codex_and_kiro_render_a_model_field(self) -> None:
        codex = tomllib.loads(generate.render(self.agent("cad-clerk"), "codex", self.MODELS))
        self.assertEqual(codex["model"], "gpt-5-mini")
        kiro = json.loads(generate.render(self.agent("cad-clerk"), "kiro", self.MODELS))
        self.assertEqual(kiro["model"], "claude-haiku-4.5")
        self.assertNotIn("model", tomllib.loads(generate.render(self.agent("cad-clerk"), "codex", {})))
        self.assertNotIn("model", json.loads(generate.render(self.agent("cad-clerk"), "kiro", {})))

    def test_untiered_agent_is_unchanged_by_a_tier_map(self) -> None:
        analyst = self.agent("cad-analyst")
        self.assertIsNone(analyst.tier)
        for harness in generate.OUTPUTS:
            with self.subTest(harness=harness):
                self.assertEqual(generate.render(analyst, harness, self.MODELS), generate.render(analyst, harness))

    def test_no_tier_models_matches_committed_output(self) -> None:
        for path, text in generate.generated().items():
            with self.subTest(path=path.name):
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_parse_tier_models_scopes_by_optional_harness_prefix(self) -> None:
        parsed = generate.parse_tier_models(["cheap=m1", "opencode:cheap=a/b#c", "kiro:strong=x:0"])
        self.assertEqual(parsed["claude"], {"cheap": "m1"})
        self.assertEqual(parsed["codex"], {"cheap": "m1"})
        self.assertEqual(parsed["opencode"], {"cheap": "a/b#c"})
        self.assertEqual(parsed["kiro"], {"cheap": "m1", "strong": "x:0"})
        self.assertNotEqual(parsed["opencode"].get("cheap"), "m1")  # bare spec skips OpenCode

    def test_parse_tier_models_rejects_bad_specs(self) -> None:
        cases = (
            ("cheap", "TIER=MODEL"),
            ("premium=m", "unknown tier"),
            ("vim:cheap=m", "unknown harness"),
            ("cheap=", "TIER=MODEL"),
            ("opencode:cheap=inherit", "inherit"),
            ("claude:cheap=inherit", "inherit"),
            ("opencode:cheap=haiku", "provider/model"),
        )
        for spec, message in cases:
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, message):
                generate.parse_tier_models([spec])


class TierSourceTests(GeneratorCopyCase):
    """Front-matter validation and the cheap-tier guard, through generate.py --check."""

    def set_tier(self, name: str, tier: str, *args: str) -> subprocess.CompletedProcess[str]:
        source = self.cad / "agents" / f"{name}.md"
        source.write_text(source.read_text(encoding="utf-8").replace("skills: [", f"tier: {tier}\nskills: [", 1), encoding="utf-8")
        return self.run_generator(*args)

    def test_rejects_unknown_tier(self) -> None:
        result = self.set_tier("cad-analyst", "premium", "--check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("tier must be one of", result.stderr)

    def test_cheap_tier_guard_rejects_reviewers_analysts_and_researchers(self) -> None:
        for name in ("cad-analyst", "cad-mech-reviewer", "cad-dfm-reviewer", "cad-sourcing-researcher"):
            with self.subTest(agent=name):
                self.setUp()
                result = self.set_tier(name, "cheap", "--check")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("never cheap", result.stderr)

    def test_non_cheap_tier_is_allowed_on_a_reviewer(self) -> None:
        result = self.set_tier("cad-mech-reviewer", "strong")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_clerk_prompt_denies_verdicts_and_cites_packets(self) -> None:
        text = (self.cad / "agents/cad-clerk.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)never issue[^.]*verdicts?")
        self.assertRegex(text, r"(?i)evidence packets?")


if __name__ == "__main__":
    unittest.main()
