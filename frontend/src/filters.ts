export type Filter = {
  people: number[];
  match: "any" | "all";
  publishers: string[];
  start: string;
  end: string;
  include_no_faces: boolean;
  sort: "newest" | "oldest";
};
export const emptyFilter = (): Filter => ({
  people: [],
  match: "any",
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
    match: q.match === "all" ? "all" : "any",
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
  if (f.people.length > 1 && f.match === "all") q.match = "all";
  if (f.publishers.length) q.publishers = f.publishers.join(",");
  if (f.start) q.start = f.start;
  if (f.end) q.end = f.end;
  if (f.include_no_faces) q.include_no_faces = "true";
  if (f.sort === "oldest") q.sort = "oldest";
  return q;
}
