import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import DateRangeHint from "../src/DateRangeHint.vue";
import { rangeError } from "../src/date-range";
describe("local date ranges", () => {
  it("compares instants rather than offset strings and accepts open bounds", () => {
    expect(rangeError("2026-01-01T08:00:00+08:00", "2026-01-01T01:00:00Z")).toBe("");
    expect(rangeError("2026-01-01T08:00:00+08:00", "2026-01-01T00:00:00Z")).toContain("晚于");
    expect(rangeError("", "2026-01-01T01:00:00Z")).toBe("");
    expect(rangeError("2026-01-01", "")).toContain("重新选择");
    expect(rangeError("2026-01-01T01:00:00", "")).toContain("重新选择");
  });
  it("shows range guidance and validation without requests", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const view = mount(DateRangeHint, { props: { start: "", end: "" } });
    expect(view.text()).toContain("包含开始，不含结束");
    await view.setProps({ start: "2026-01-01" });
    expect(view.text()).toContain("重新选择");
    expect(fetch).not.toHaveBeenCalled();
    view.unmount(); vi.unstubAllGlobals();
  });
});
