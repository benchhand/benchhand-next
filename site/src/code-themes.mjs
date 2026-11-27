// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The syntax themes of every code block, from the site's tokens (src/styles/theme.css): code text on the
// code background, keys and keywords in the ink blue, strings in a brown, comments in the muted grey.
// Every pair is at least 6.2:1, so Expressive Code's minimum contrast (5.5:1) leaves the colours alone.
// Starlight shows the light theme under [data-theme="light"] and the dark one under [data-theme="dark"].

const KEY_SCOPES = [
  "keyword",
  "storage",
  "entity.name.tag",
  "entity.name.function",
  "entity.name.type",
  "support.function",
  "support.type.property-name",
  "variable.other.property",
  "meta.object-literal.key",
];
const STRING_SCOPES = ["string", "string.unquoted", "constant.other.symbol"];
const COMMENT_SCOPES = ["comment", "punctuation.definition.comment"];

/** @param {"light" | "dark"} type @param {Record<string, string>} colour */
function theme(type, colour) {
  return {
    name: `benchhand-${type}`,
    type,
    colors: {
      "editor.background": colour.background,
      "editor.foreground": colour.text,
      "editor.selectionBackground": colour.selection,
    },
    tokenColors: [
      { settings: { foreground: colour.text } },
      { scope: KEY_SCOPES, settings: { foreground: colour.key } },
      { scope: STRING_SCOPES, settings: { foreground: colour.string } },
      { scope: COMMENT_SCOPES, settings: { foreground: colour.comment, fontStyle: "" } },
    ],
  };
}

export const codeThemeLight = theme("light", {
  background: "#eae7dc",
  text: "#17202c",
  key: "#1b4b9b",
  string: "#8a3a12",
  comment: "#4a5262",
  selection: "#d3cfc2",
});

export const codeThemeDark = theme("dark", {
  background: "#08131f",
  text: "#e6edf5",
  key: "#8fc3ff",
  string: "#ffc58f",
  comment: "#a6b5c8",
  selection: "#223a57",
});
