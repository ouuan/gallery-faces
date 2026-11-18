import { describe, it, expect, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { emptyFilter, fromQuery, toQuery } from "../src/filters";
import { publisherLabel, platformLabel, type Person } from "../src/api";
import SourceText from "../src/SourceText.vue";
describe("gallery state", () => {
  it("restores filters and excludes no-face images on clear", () => {
    const f = {
      ...emptyFilter(),
      people: [1, 2],
      publishers: ["person:3", "x:someone"],
      include_no_faces: true,
      start: "2026-01-01",
      match: "all" as const,
    };
    expect(fromQuery(toQuery(f))).toEqual(f);
    expect(toQuery(emptyFilter())).toEqual({});
  });
  it.each([{ people: [] }, { people: [1] }, { people: [1, 2] }])("preserves all-person matching for $people", ({ people }) => {
    const filter = { ...emptyFilter(), people, match: "all" as const };
    expect(fromQuery(toQuery(filter))).toEqual(filter);
  });
  it("renders source text safely while preserving links and newlines", () => {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    const wrapper = mount(SourceText, {
      props: { text: "<script>alert(1)</script>\n🐈 https://example.com" },
    });
    expect(wrapper.find("script").exists()).toBe(false);
    expect(wrapper.find("a").attributes("href")).toBe("https://example.com");
    expect(wrapper.text()).toContain("🐈");
    expect(wrapper.find("p").classes()).toContain("clamped");
    wrapper.unmount();
    vi.unstubAllGlobals();
  });
});

it("shows linked person names before platform nicknames, with safe fallback", () => {
  const people = [
    { id: 1, name: "人物名", accounts: [{ platform: "x", username: "ALICE" }] },
  ] as Person[];
  const source = {
    platform: "x",
    author: "alice",
    author_name: "平台昵称",
    url: "",
    published_at: "",
  };
  expect(publisherLabel(source, people)).toBe("人物名");
  expect(publisherLabel(source, [])).toBe("平台昵称");
  expect(publisherLabel({ ...source, platform: "instagram" }, people)).toBe(
    "平台昵称",
  );
  expect(publisherLabel({ ...source, author_name: null }, [])).toBe("alice");
  expect(platformLabel("x")).toBe("X");
});
