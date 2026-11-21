import { groupPeople } from "./person-groups";
import type { Person } from "./api";

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

export function updatePeople(
  keys: (string | number)[] | null,
  current: number[],
  options: PeopleGroupOption[],
) {
  if (!keys?.length) return [];
  const incoming = new Set(keys);
  const checked = new Set(
    options.flatMap((group) =>
      group.children
        .filter(
          (person) => incoming.has(group.value) || incoming.has(person.value),
        )
        .map((person) => person.value),
    ),
  );
  const previous = new Set(peopleKeys(current, options));
  const next = new Set(current);
  for (const person of options.flatMap((group) => group.children)) {
    if (checked.has(person.value) && !previous.has(person.value))
      next.add(person.personId);
  }
  // Removing an alias removes the person from every group, even when another
  // alias is still present in the component's emitted selection.
  for (const person of options.flatMap((group) => group.children)) {
    if (previous.has(person.value) && !checked.has(person.value))
      next.delete(person.personId);
  }
  return [...next];
}
