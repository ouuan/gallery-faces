import type { components } from "./schema";

export type GroupName = components["schemas"]["GroupName"];
export type SelectedGroup = number | GroupName;

export const emptyGroup = () => ({ name: "", name_ja: "" });

export function personGroupPayload(selected: SelectedGroup[], draft: GroupName) {
  const newGroups = selected.filter((group): group is GroupName => typeof group !== "number");
  return {
    group_ids: selected.filter((group): group is number => typeof group === "number"),
    new_groups: draft.name.trim() ? [...newGroups, draft] : newGroups,
  };
}
