import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { describe, expect, it, vi } from "vitest";
import { useReviewShortcuts } from "../src/review-shortcuts";

describe("review shortcuts", () => {
  it("respects keyboard ownership, modifiers, busy state and lifecycle", () => {
    let enabled = true;
    const run = vi.fn();
    const wrapper = mount(defineComponent({
      setup() { useReviewShortcuts({ c: { run } }, () => enabled); return () => null; },
    }));
    const press = (init: KeyboardEventInit = {}, target: EventTarget = window) => {
      const event = new KeyboardEvent("keydown", { key: "c", bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event;
    };
    for (const init of [{ repeat: true }, { isComposing: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }, { key: "z" }])
      expect(press(init).defaultPrevented).toBe(false);
    const consumed = new KeyboardEvent("keydown", { key: "c", cancelable: true });
    consumed.preventDefault(); window.dispatchEvent(consumed);
    enabled = false; press(); enabled = true;
    for (const html of ['<input>', '<textarea></textarea>', '<select></select>', '<div contenteditable="true" tabindex="0"></div>', '<div role="combobox" tabindex="0"></div>', '<input type="radio">', '<input type="checkbox">']) {
      const host = document.createElement("div"); host.innerHTML = html; document.body.append(host);
      const control = host.firstElementChild as HTMLElement; control.focus();
      press({}, control); press(); host.remove();
    }
    const dialog = document.createElement("div"); dialog.setAttribute("role", "alertdialog");
    document.body.append(dialog);
    vi.spyOn(dialog, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
    press(); dialog.remove();
    expect(run).not.toHaveBeenCalled();
    expect(press({ key: "C" }).defaultPrevented).toBe(true);
    expect(run).toHaveBeenCalledTimes(1);
    wrapper.unmount(); press(); expect(run).toHaveBeenCalledTimes(1);
  });
});
