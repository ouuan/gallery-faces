import { onMounted, onUnmounted } from "vue";

type Shortcut = { run: () => unknown; enabled?: () => boolean };
const controls = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="listbox"], [role="radio"], [role="checkbox"], .n-base-selection, .n-cascader, .n-select';

export function useReviewShortcuts(
  shortcuts: Record<string, Shortcut>,
  enabled: () => boolean,
) {
  function keydown(event: KeyboardEvent) {
    if (event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229 ||
        event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || !enabled()) return;
    const shortcut = shortcuts[event.key.toLowerCase()];
    if (!shortcut || shortcut.enabled?.() === false) return;
    if ([event.target, document.activeElement].some(target =>
      target instanceof Element && target.closest(controls))) return;
    // Include provider-created confirmation dialogs as well as local modals.
    if (Array.from(document.querySelectorAll('[role="dialog"], [role="alertdialog"], [aria-modal="true"]'))
      .some(dialog => dialog.getClientRects().length && getComputedStyle(dialog).visibility !== "hidden")) return;
    event.preventDefault();
    void shortcut.run();
  }
  onMounted(() => window.addEventListener("keydown", keydown));
  onUnmounted(() => window.removeEventListener("keydown", keydown));
}
