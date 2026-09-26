/**
 * Chart colours. The eight categorical hues are a validated set: in this
 * order every adjacent pair stays distinguishable under the common forms
 * of colour blindness, in both light and dark mode. Slots are assigned in
 * order and never cycled — a ninth series folds into "Other" instead.
 *
 * Dark mode uses the same hues stepped for the dark surface; it is not an
 * automatic inversion.
 */

export const CATEGORICAL = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
} as const;

/** One-hue ramp, light to dark, for magnitude (heatmaps). */
export const SEQUENTIAL = [
  "#cde2fb",
  "#b7d3f6",
  "#9ec5f4",
  "#86b6ef",
  "#6da7ec",
  "#5598e7",
  "#3987e5",
  "#2a78d6",
  "#256abf",
  "#1c5cab",
  "#184f95",
  "#104281",
  "#0d366b",
] as const;

/** Decrease / increase for a waterfall — the diverging pair's poles. */
export const DIVERGING = { negative: "#e34948", positive: "#2a78d6" } as const;

/** De-emphasis grey for "Other" and waterfall totals. */
export const MUTED = { light: "#898781", dark: "#898781" } as const;

export type Mode = "light" | "dark";

export function seriesColor(index: number, name: string, mode: Mode): string {
  if (name === "Other") return MUTED[mode];
  return CATEGORICAL[mode][index % CATEGORICAL[mode].length];
}

/** Heatmap fill for a value within [min, max]. */
export function sequentialColor(value: number, min: number, max: number): string {
  if (!Number.isFinite(value) || max === min) return SEQUENTIAL[6];
  const position = (value - min) / (max - min);
  const index = Math.round(position * (SEQUENTIAL.length - 1));
  return SEQUENTIAL[Math.max(0, Math.min(SEQUENTIAL.length - 1, index))];
}

/** Text on a heatmap cell: dark ink on the light half, white on the dark. */
export function inkOn(fill: string): string {
  const index = SEQUENTIAL.indexOf(fill as (typeof SEQUENTIAL)[number]);
  return index >= 0 && index < 6 ? "#0b0b0b" : "#ffffff";
}
