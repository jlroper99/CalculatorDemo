import { describe, expect, it } from "vitest";

import { formatSpeed, mpsTo, toMps } from "./units";

describe("speed units", () => {
  it("converts m/s to mph and km/h", () => {
    expect(mpsTo("mph", 29.09)).toBeCloseTo(65.07, 2);
    expect(mpsTo("kmh", 10)).toBeCloseTo(36, 10);
  });

  it("round-trips", () => {
    for (const unit of ["mph", "kmh"] as const) {
      expect(toMps(unit, mpsTo(unit, 18.1))).toBeCloseTo(18.1, 10);
    }
  });

  it("formats with a unit label", () => {
    expect(formatSpeed(26.8224, "mph")).toBe("60 mph");
    expect(formatSpeed(13.8889, "kmh", 1)).toBe("50.0 km/h");
  });
});
