// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Starlight's mobile menu button opens the sidebar as a popover (popovertarget) and sets no aria-expanded,
// so a screen reader isn't told whether the menu is open. The button's aria-expanded follows the popover.
const sidebar = document.getElementById("starlight__sidebar");
const buttons = document.querySelectorAll<HTMLElement>('button[popovertarget="starlight__sidebar"]');

function updateExpanded(): void {
  const open = sidebar?.matches(":popover-open") ?? false;
  for (const button of buttons) button.setAttribute("aria-expanded", String(open));
}

if (sidebar) {
  updateExpanded();
  sidebar.addEventListener("toggle", updateExpanded);
}
