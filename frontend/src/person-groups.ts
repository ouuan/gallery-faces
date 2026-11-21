import type { components } from "./schema";
import type { Person } from "./api";
import { t } from "./locale";

export type GroupName = components["schemas"]["GroupName"];
export type SelectedGroup = number | GroupName;

export const emptyGroup = () => ({ name: "", name_ja: "" });

export function groupPeople(people: Person[], groups: { id: number; name: string }[]) {
  const sections = [...groups, { id: 0, name: t("未分组") }].map((group) => ({
    ...group, members: [] as Person[],
  }));
  const byId = new Map(sections.map((section) => [section.id, section]));
  for (const person of people) {
    if (!person.groups.length) byId.get(0)!.members.push(person);
    for (const group of person.groups) byId.get(group.id)?.members.push(person);
  }
  return sections.filter((section) => section.members.length);
}

export function personGroupPayload(selected: SelectedGroup[], draft: GroupName) {
  const newGroups = selected.filter((group): group is GroupName => typeof group !== "number");
  return {
    group_ids: selected.filter((group): group is number => typeof group === "number"),
    new_groups: draft.name.trim() ? [...newGroups, draft] : newGroups,
  };
}
