export type Filter = {
  people: number[];
  match: "any" | "all";
  onlySelected: boolean;
  publishers: string[];
  start: string;
  end: string;
  include_no_faces: boolean;
  sort: "newest" | "oldest";
};
export const emptyFilter = (): Filter => ({
  people: [],
  match: "any",
  onlySelected: false,
  publishers: [],
  start: "",
  end: "",
  include_no_faces: false,
  sort: "newest",
});
function expandIds(tokens: string[]) {
  const ids: number[] = [];
  for (const token of tokens) {
    const range = /^(\d+)(?:-(\d+))?$/.exec(token);
    if (!range) continue;
    const first = Number(range[1]), last = Number(range[2] ?? range[1]);
    if (!Number.isSafeInteger(last) || first < 1 || first > last || last - first + 1 > 4096 - ids.length) continue;
    for (let id = first; id <= last; id++) ids.push(id);
  }
  return [...new Set(ids)];
}

function compactIds(ids: number[]) {
  const sorted = [...new Set(ids)].sort((left, right) => left - right);
  const ranges: string[] = [];
  for (let index = 0; index < sorted.length; index++) {
    const first = sorted[index];
    while (sorted[index + 1] === sorted[index] + 1) index++;
    const last = sorted[index];
    ranges.push(first === last ? String(first) : `${first}-${last}`);
  }
  return ranges;
}

function publisherParts(values: string[]) {
  return {
    people: values.filter(value => value.startsWith('person:')).map(value => value.slice(7)),
    accounts: values.filter(value => !value.startsWith('person:')),
  };
}

export function fromQuery(q: Record<string, any>): Filter {
  const publishers = publisherParts(String(q.publishers || '').split(',').filter(Boolean));
  return {
    people: expandIds(String(q.people || '').split(',')),
    match: q.match === "all" || q.match === "exact" ? "all" : "any",
    onlySelected: q.match === "subset" || q.match === "exact",
    publishers: [...expandIds(publishers.people).map(id => `person:${id}`), ...publishers.accounts],
    start: String(q.start || ""),
    end: String(q.end || ""),
    include_no_faces: q.include_no_faces === "true",
    sort: q.sort === "oldest" ? "oldest" : "newest",
  };
}
export function toQuery(f: Filter) {
  const q: Record<string, string> = {};
  if (f.people.length) q.people = compactIds(f.people).join(',');
  if (f.onlySelected) q.match = f.match === "all" ? "exact" : "subset";
  else if (f.match === "all") q.match = "all";
  if (f.publishers.length) {
    const { people, accounts } = publisherParts(f.publishers);
    q.publishers = [...compactIds(people.map(Number)).map(range => `person:${range}`), ...accounts].join(',');
  }
  if (f.start) q.start = f.start;
  if (f.end) q.end = f.end;
  if (f.include_no_faces) q.include_no_faces = "true";
  if (f.sort === "oldest") q.sort = "oldest";
  return q;
}

export const hasFilters = (f: Filter) => Boolean(
  f.people.length || f.publishers.length || f.start || f.end || f.include_no_faces
);
export const clearFilters = (f: Filter): Filter => ({ ...emptyFilter(), sort: f.sort });

export const filterOnlyQuery = (filter: Filter) => toQuery({ ...filter, sort: 'newest' });

export function feedHref(filter: Filter) {
  const query = new URLSearchParams(filterOnlyQuery(filter)).toString();
  return '/api/v1/gallery/rss.xml' + (query ? '?' + query : '');
}

export const publisherRoute = (platform: string, author: string) => ({
  path: '/', query: { publishers: `${platform}:${author}` },
});
