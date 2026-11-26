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
export function fromQuery(q: Record<string, any>): Filter {
  return {
    people: String(q.people || "")
      .split(",")
      .filter(Boolean)
      .map(Number)
      .filter(Number.isFinite),
    match: q.match === "all" || q.match === "exact" ? "all" : "any",
    onlySelected: q.match === "subset" || q.match === "exact",
    publishers: String(q.publishers || "")
      .split(",")
      .filter(Boolean),
    start: String(q.start || ""),
    end: String(q.end || ""),
    include_no_faces: q.include_no_faces === "true",
    sort: q.sort === "oldest" ? "oldest" : "newest",
  };
}
export function toQuery(f: Filter) {
  const q: Record<string, string> = {};
  if (f.people.length) q.people = f.people.join(",");
  if (f.onlySelected) q.match = f.match === "all" ? "exact" : "subset";
  else if (f.match === "all") q.match = "all";
  if (f.publishers.length) q.publishers = f.publishers.join(",");
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
