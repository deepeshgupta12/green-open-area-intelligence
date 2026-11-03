import type { MetricSource, MetricValue } from "../types";

const SQ_M_TO_SQ_FT = 10.763910417;

const indian = (digits: number) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export function fmt(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return indian(digits).format(value);
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 1_00_000) return `${indian(1).format(value / 1_00_000)} L`;
  if (Math.abs(value) >= 1_000) return `${indian(1).format(value / 1_000)}K`;
  return indian(0).format(value);
}

export function fmtPercent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${indian(digits).format(value)}%`;
}

export function fmtSqM(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : `${indian(digits).format(value)} sq.m`;
}

export function sqMToSqFt(value: number | null | undefined): number | null {
  return value === null || value === undefined ? null : value * SQ_M_TO_SQ_FT;
}

export function fmtSqMWithFt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${indian(digits).format(value)} sq.m (${indian(0).format(value * SQ_M_TO_SQ_FT)} sq.ft)`;
}

export function metricValue(metric: MetricValue | undefined | null): number | null {
  return metric && metric.value !== null && metric.value !== undefined ? metric.value : null;
}

export function isAvailable(metric: MetricValue | undefined | null): boolean {
  return metricValue(metric) !== null;
}

const SOURCE_LABELS: Record<MetricSource, string> = {
  project_records: "From project records",
  master_plan_estimate: "Estimated from the master plan",
  master_plan_entities: "Counted on the master plan",
  derived: "Derived",
  benchmark_dataset: "Benchmark dataset",
  unavailable: "Not in project records",
};

export function sourceLabel(metric: MetricValue | undefined | null): string {
  if (!metric) return SOURCE_LABELS.unavailable;
  const base = SOURCE_LABELS[metric.source] ?? metric.source;
  return metric.confidence_label && metric.source !== "project_records"
    ? `${base} · ${metric.confidence_label} confidence`
    : base;
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .toLowerCase()
    .split(/\s+/)
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}
