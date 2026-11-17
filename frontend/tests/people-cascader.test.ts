import { describe, expect, it } from "vitest";
import {
  peopleOptions,
  peopleKeys,
  updatePeople,
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
    expect(updatePeople(["group:0"], [], options)).toEqual([4]);
  });
  it("selects overlapping groups without duplicate people", () => {
    expect(updatePeople(["group:1", "group:2"], [], options)).toEqual([
      1, 2, 3,
    ]);
    expect(updatePeople(["group:1", "group:2:person:1"], [1], options)).toEqual(
      [1, 2],
    );
  });
  it("deselects aliases everywhere and preserves unrelated selected people", () => {
    expect(
      updatePeople(["group:1:person:2", "group:2:person:1"], [1, 2], options),
    ).toEqual([2]);
    expect(updatePeople(["group:2"], [1, 2, 3], options)).toEqual([3]);
    expect(updatePeople([], [1, 2], options)).toEqual([]);
  });
});
