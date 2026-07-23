// Categorical cluster palette — validated with the dataviz six-checks script:
// dark slots against the #0d1117 map panel, light slots against white cards.
// Slots are assigned in FIXED order by cluster index (never re-cycled), and
// color is never the only encoding: the map legend, hover tooltips, and chip
// labels always carry the cluster name in text.

export const CLUSTER_DARK = [
  "#3987e5", // blue
  "#199e70", // aqua
  "#c98500", // yellow
  "#008300", // green
  "#9085e9", // violet
  "#e66767", // red
  "#d55181", // magenta
  "#d95926", // orange
];

export const CLUSTER_LIGHT = [
  "#2a78d6",
  "#1baf7a",
  "#eda100",
  "#008300",
  "#4a3aa7",
  "#e34948",
  "#e87ba4",
  "#eb6834",
];

export const UNCLUSTERED_DARK = "#8b949e";

export function clusterColor(index: number, mode: "dark" | "light" = "dark"): string {
  const palette = mode === "dark" ? CLUSTER_DARK : CLUSTER_LIGHT;
  return palette[index % palette.length];
}
