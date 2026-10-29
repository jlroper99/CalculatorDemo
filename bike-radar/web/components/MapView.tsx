"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";

import { INITIAL_VIEW } from "@/lib/config";

// Placeholder style with no external tiles. Segment and pass layers arrive in M3.
const EMPTY_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#e8ecef" } }],
};

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: EMPTY_STYLE,
      center: INITIAL_VIEW.center,
      zoom: INITIAL_VIEW.zoom,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => map.remove();
  }, []);

  return <div ref={container} data-testid="map" className="map" />;
}
