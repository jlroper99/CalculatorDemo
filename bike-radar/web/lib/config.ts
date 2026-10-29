export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Initial view: Utah County. Basemap tiles are chosen in M3 (features/003).
export const INITIAL_VIEW = { center: [-111.66, 40.23] as [number, number], zoom: 10 };
