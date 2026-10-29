import MapView from "@/components/MapView";
import { API_URL } from "@/lib/config";

export default function Home() {
  return (
    <main className="layout">
      <header className="topbar">
        <h1>Bike Radar Danger Map</h1>
        <nav>
          <a href={`${API_URL}/docs`}>API</a>
        </nav>
      </header>
      <MapView />
      <footer className="disclaimer">
        Radar speeds are uncalibrated estimates (3 m/s buckets). Not for identifying drivers.
      </footer>
    </main>
  );
}
