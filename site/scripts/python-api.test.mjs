// What counts as public in the Python API pages (publicNames in python-api.mjs).
import assert from "node:assert/strict";
import { test } from "node:test";

import { publicNames } from "./python-api.mjs";

test("a module with __all__ is public by __all__, including names imported from elsewhere", () => {
  const module = {
    exports: ["validate", "Finding"],
    members: { validate: { kind: "function" }, Finding: { kind: "alias" }, helper: { kind: "function" } },
  };
  assert.deepEqual(publicNames(module), ["validate", "Finding"]);
});

test("a module without __all__ is public by name: a function or class, no leading underscore, defined here", () => {
  const module = {
    exports: null,
    members: {
      run: { kind: "function" },
      Runner: { kind: "class" },
      LIMIT: { kind: "attribute" },
      _private: { kind: "function" },
      __version__: { kind: "attribute" },
      imported: { kind: "alias" },
      submodule: { kind: "module" },
    },
  };
  assert.deepEqual(publicNames(module), ["run", "Runner"]);
});

test("an empty module has no public names", () => {
  assert.deepEqual(publicNames({ exports: null }), []);
});
