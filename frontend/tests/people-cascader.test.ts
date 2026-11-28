import { describe, expect, it } from "vitest";
import {
  peopleOptions,
  peopleKeys,
  pickerIndex,
} from "../src/people-cascader";
import type { Person } from "../src/api";

const groups = [
  { id: 1, name: "朋友" },
  { id: 2, name: "同事" },
  { id: 3, name: "空组" },
];
const people = [
  { id: 1, name: "共同成员", groups: groups.slice(0, 2) },
  { id: 2, name: "朋友甲", groups: [groups[0]] },
  { id: 3, name: "同事乙", groups: [groups[1]] },
  { id: 4, name: "独立人物", groups: [] },
] as Person[];
const options = peopleOptions(people, groups);

describe("people cascader selection", () => {
  it("preserves all memberships with distinct keys and an ungrouped branch", () => {
    expect(options.map((g) => g.label)).toEqual(["朋友", "同事", "未分组"]);
    expect(peopleKeys([1], options)).toEqual([
      "group:1:person:1",
      "group:2:person:1",
    ]);
    expect(pickerIndex(options).members.get("group:0")).toEqual(["person:4"]);
  });
  it("represents each person exactly once even when whole groups overlap", () => {
    const index = pickerIndex(options);
    for (const ids of [[1], [1, 3], [1, 2, 3, 4]]) {
      const selected = ids.map(id => `person:${id}`);
      const tags = index.tagKeys(new Set(selected));
      expect(tags.flatMap(key => index.members.get(key)!).sort()).toEqual(selected);
    }
  });
  it("summarizes complete groups once and keeps partial and unknown selections visible", () => {
    const { tagLabels } = pickerIndex(options);
    const selected = new Set(["person:3", "person:2", "person:1", "person:99", "x:alice"]);
    expect(tagLabels(selected, value => value)).toEqual(["朋友", "同事乙", "person:99", "x:alice"]);
  });
  it("deduplicates name and group matches by identity, not by name", () => {
    const namedAlike = peopleOptions([...people, { ...people[0], id: 5 }], groups);
    const { filter } = pickerIndex(namedAlike);
    const search = (query: string) => namedAlike.flatMap(group => group.children
      .filter(child => filter(query, child, [group, child])).map(child => child.personId));
    expect(search("共同")).toEqual([1, 5]);
    expect(search("同事")).toEqual([1, 3, 5]);
  });
});
