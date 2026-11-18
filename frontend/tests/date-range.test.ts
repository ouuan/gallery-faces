import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import DateRangeHint from "../src/DateRangeHint.vue";
import { utcOffset, dateRangeLabel, type DateBounds } from "../src/date-range";
const empty: DateBounds = { timezone: "Asia/Shanghai", start: null, end: null, current_offset_seconds: 28800 };
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe("date range hints", () => {
  it.each([[0, "UTC+0"], [28800, "UTC+8"], [-18000, "UTC-5"], [19800, "UTC+5:30"], [20700, "UTC+5:45"]])("formats %s seconds", (seconds, expected) => {
    expect(utcOffset(seconds as number)).toBe(expected);
  });
  it("labels actual exclusive end boundaries across DST", () => {
    expect(dateRangeLabel(empty)).toBe("当前按 UTC+8 计算");
    const start = { utc: "2026-03-08T05:00:00Z", offset_seconds: -18000 };
    const end = { utc: "2026-03-09T04:00:00Z", offset_seconds: -14400 };
    expect(dateRangeLabel({ ...empty, start, end })).toBe("开始：当日 00:00（UTC-5）；结束：次日 00:00（UTC-4），不含该时刻");
    expect(dateRangeLabel({ ...empty, start })).toBe("开始：当日 00:00（UTC-5）");
    expect(dateRangeLabel({ ...empty, end })).toBe("结束：次日 00:00（UTC-4），不含该时刻");
  });
  it("debounces, shares concurrent requests, and discards stale results", async () => {
    vi.useFakeTimers();
    const pending: ((value: unknown) => void)[] = [];
    const fetch = vi.fn(() => new Promise(resolve => pending.push(resolve)));
    vi.stubGlobal("fetch", fetch);
    const a = mount(DateRangeHint, { props: { start: "", end: "" } });
    const b = mount(DateRangeHint, { props: { start: "", end: "" } });
    await vi.advanceTimersByTimeAsync(250);
    expect(fetch).toHaveBeenCalledTimes(1);
    await a.setProps({ start: "2026-01-01" });
    await a.setProps({ start: "2026-01-02" });
    await vi.advanceTimersByTimeAsync(250);
    expect(fetch).toHaveBeenCalledTimes(2);
    pending[1]({ ok: true, json: async () => ({ ...empty, start: { utc: "2026-01-01T16:00:00Z", offset_seconds: 28800 } }) });
    await flushPromises();
    pending[0]({ ok: true, json: async () => empty });
    await flushPromises();
    expect(a.text()).toContain("开始：当日 00:00（UTC+8）");
    expect(b.text()).toBe("当前按 UTC+8 计算");
    a.unmount(); b.unmount();
  });
  it("clears stale hints on failure and permits retry", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({ ok: true, json: async () => empty });
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(DateRangeHint, { props: { start: "", end: "" } });
    await vi.advanceTimersByTimeAsync(250);
    expect(wrapper.text()).toContain("时区信息加载失败");
    await wrapper.get("button").trigger("click");
    await vi.advanceTimersByTimeAsync(250);
    expect(wrapper.text()).toBe("当前按 UTC+8 计算");
    wrapper.unmount();
  });
});
