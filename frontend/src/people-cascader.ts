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
  function tags(selected: Set<string>) {
    const fullGroups = groups.filter(group => group.children.length && members.get(group.value)!.every(id => selected.has(id)));
    const coverage = new Map<string, number>();
    for (const group of fullGroups) {
      for (const id of members.get(group.value)!) coverage.set(id, (coverage.get(id) ?? 0) + 1);
    }
    const keys = new Set<string>();
    for (const group of fullGroups.reverse().sort((left, right) => left.children.length - right.children.length)) {
      const ids = members.get(group.value)!;
      if (ids.every(id => coverage.get(id)! > 1)) {
        for (const id of ids) coverage.set(id, coverage.get(id)! - 1);
      } else {
        keys.add(group.value);
      }
    }
    for (const id of selected) {
      if (coverage.has(id)) continue;
      const alias = aliases.get(id)?.[0];
      if (alias) keys.add(alias.key);
    }
    return groups.flatMap<{ value: string; label: string }>(group => keys.has(group.value) ? [group]
      : group.children.filter(child => keys.has(child.value)));
  }
  function tagLabels(selected: Set<string>, fallback: (id: string) => string) {
    return [...tags(selected).map(tag => tag.label), ...[...selected].filter(id => !aliases.has(id)).map(fallback)];
  }
  return { members, tagKeys: (selected: Set<string>) => tags(selected).map(tag => tag.value), tagLabels, filter };
}
