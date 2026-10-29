// Values are stored in SI (m/s); conversion happens only at display time (AGENTS.md).

export type SpeedUnit = "mph" | "kmh";

export const MPS_PER_MPH = 0.44704;
export const MPS_PER_KMH = 1 / 3.6;

export function mpsTo(unit: SpeedUnit, mps: number): number {
  return unit === "mph" ? mps / MPS_PER_MPH : mps / MPS_PER_KMH;
}

export function toMps(unit: SpeedUnit, value: number): number {
  return unit === "mph" ? value * MPS_PER_MPH : value * MPS_PER_KMH;
}

export function formatSpeed(mps: number, unit: SpeedUnit, digits = 0): string {
  const label = unit === "mph" ? "mph" : "km/h";
  return `${mpsTo(unit, mps).toFixed(digits)} ${label}`;
}
