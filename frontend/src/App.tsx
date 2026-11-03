import { MasterPlanSourceCard } from "./components/MasterPlanSourceCard";
import "./styles.css";

export default function App() {
  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Square Yards Internal Intelligence</p>
          <h1>Master Plan Intelligence</h1>
          <p>
            Paste a master plan image link or upload the image, and the model locates every wing, amenity, road,
            gate and utility on the plan. Add the project&apos;s Datacenter JSON to get the site zoning, density and
            land allocation views built from key-value facts with their sources.
          </p>
        </div>
      </section>

      <section className="explorer-section">
        <MasterPlanSourceCard />
      </section>
    </main>
  );
}
