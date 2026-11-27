// The phases of docs/design-plan.md's "Steps (phased)" list, parsed from the plan itself.
// A placeholder page's `phase` front matter must name one of them.
import { readFileSync } from "node:fs";

import { repoUrl } from "./site-url.mjs";

const PLAN = "docs/design-plan.md";
const STEPS_HEADING = "## Steps (phased)";
const PHASE_ITEM = /^- \[[ x]\] \*\*Phase (\d+): (.+?)\.?\*\*/;

// The plan's Steps section on GitHub. The phases are list items, so they have no anchors of their own.
export const planStepsUrl = `${repoUrl}/blob/main/${PLAN}#steps-phased`;

/** @returns {Map<number, string>} phase number → its title, such as 2 → "flow engine" */
export function planPhases() {
  const lines = readFileSync(new URL(`../${PLAN}`, import.meta.url), "utf8").split("\n");
  const start = lines.indexOf(STEPS_HEADING);
  if (start < 0) throw new Error(`${PLAN} has no "${STEPS_HEADING}" section`);
  const phases = new Map();
  for (const line of lines.slice(start + 1)) {
    if (line.startsWith("## ")) break;
    const match = line.match(PHASE_ITEM);
    if (match) phases.set(Number(match[1]), match[2]);
  }
  if (phases.size === 0) throw new Error(`${PLAN}'s "${STEPS_HEADING}" lists no phases`);
  return phases;
}
