import { groupPeople } from "./person-groups";
import type { Person } from "./api";
import type { CascaderOption } from "naive-ui";

export type PeopleGroupOption = {
  label: string;
  value: string;
  children: { label: string; value: string; personId: number }[];
};

export function peopleOptions(
  people: Person[],
  groups: { id: number; name: string }[],
): PeopleGroupOption[] {
  return groupPeople(people, groups).map((group) => ({
    label: group.name,
    value: `group:${group.id}`,
    children: group.members.map((person) => ({
      label: person.name,
      value: `group:${group.id}:person:${person.id}`,
      personId: person.id,
    })),
  }));
}

export function peopleKeys(ids: number[], options: PeopleGroupOption[]) {
  const selected = new Set(ids);
  return options.flatMap((group) =>
    group.children
      .filter((person) => selected.has(person.personId))
      .map((person) => person.value),
  );
}

type PickerGroup = {
  label: string;
  value: string;
  children: { label: string; value: string; personId?: number }[];
};

export function pickerIndex(groups: PickerGroup[]) {
  const members = new Map<string, string[]>();
  const aliases = new Map<string, { key: string; groupName: string }[]>();
  for (const group of groups) {
    members.set(group.value, group.children.map((child) => {
      const id = child.personId == null ? child.value : `person:${child.personId}`;
      members.set(child.value, [id]);
      const paths = aliases.get(id) ?? [];
      paths.push({ key: child.value, groupName: group.label.toLowerCase() });
      aliases.set(id, paths);
      return id;
    }));
  }
  function filter(pattern: string, option: CascaderOption, path: CascaderOption[]) {
    const query = pattern.toLowerCase();
    if (!path.some(node => node.label?.toLowerCase().includes(query))) return false;
    if (path.length === 1) return true;
    const paths = aliases.get(members.get(String(option.value))![0])!;
    const match = option.label?.toLowerCase().includes(query)
      ? paths[0] : paths.find(alias => alias.groupName.includes(query));
    return match?.key === option.value;
  }
  function tagKeys(selected: Set<string>) {
    const remaining = new Set(selected);
    const keys = new Set<string>();
    for (const group of groups) {
      const ids = members.get(group.value)!;
      if (ids.length && ids.every(id => remaining.has(id))) {
        keys.add(group.value);
        ids.forEach(id => remaining.delete(id));
      }
    }
    for (const id of remaining) {
      const alias = aliases.get(id)?.[0];
      if (alias) keys.add(alias.key);
    }
    return groups.flatMap(group => keys.has(group.value) ? [group.value]
      : group.children.filter(child => keys.has(child.value)).map(child => child.value));
  }
  return { members, tagKeys, filter };
}
