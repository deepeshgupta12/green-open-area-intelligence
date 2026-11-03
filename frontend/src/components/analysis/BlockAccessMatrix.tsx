import { useState } from "react";
import { Check } from "lucide-react";
import type { ResidentialBlockProximity } from "../../types";
import { fmt } from "../../lib/format";

const COLLAPSED_ROWS = 8;

type BlockAccessMatrixProps = {
  blocks: ResidentialBlockProximity[];
};

const FLAGS: Array<{ key: keyof ResidentialBlockProximity; label: string }> = [
  { key: "near_entry_gate", label: "Entry gate" },
  { key: "near_external_road", label: "External road" },
  { key: "near_parking", label: "Parking" },
  { key: "near_utility_yard", label: "Utility yard" },
];

/** One hue, light to dark with the count; zero stays on the surface. */
function shade(value: number, max: number): string | undefined {
  if (value <= 0) return undefined;
  const t = max > 0 ? value / max : 0;
  return `rgba(0, 131, 0, ${(0.1 + 0.32 * t).toFixed(2)})`;
}

export function BlockAccessMatrix({ blocks }: BlockAccessMatrixProps) {
  const [expanded, setExpanded] = useState(false);
  if (blocks.length === 0) return null;

  const maxAmenities = Math.max(...blocks.map((block) => block.nearby_amenities.length));
  const maxGreen = Math.max(...blocks.map((block) => block.nearby_green.length));
  const scored = blocks.map((block) => ({ block, score: block.nearby_amenities.length + block.nearby_green.length }));
  const best = scored.reduce((a, b) => (b.score > a.score ? b : a));
  const least = scored.reduce((a, b) => (b.score < a.score ? b : a));
  const sorted = [...blocks].sort((a, b) => a.block_label.localeCompare(b.block_label, undefined, { numeric: true }));
  const collapsible = sorted.length > COLLAPSED_ROWS + 2;
  const shown = collapsible && !expanded ? sorted.slice(0, COLLAPSED_ROWS) : sorted;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <div>
          <h4>Block-by-block access</h4>
          <p className="analysis-subtitle">What sits within a short walk of each residential block, read from positions on the plan.</p>
        </div>
      </div>

      {best.block !== least.block && best.score !== least.score && (
        <p className="zoning-lead">
          <strong>{best.block.block_label}</strong> is the best-served block, with {fmt(best.block.nearby_amenities.length)}{" "}
          amenities and {fmt(best.block.nearby_green.length)} green spaces nearby; <strong>{least.block.block_label}</strong>{" "}
          has the fewest, with {fmt(least.block.nearby_amenities.length)} and {fmt(least.block.nearby_green.length)}.
        </p>
      )}

      <div className="chart-table-wrap">
        <table className="access-matrix">
          <thead>
            <tr>
              <th scope="col">Block</th>
              <th scope="col">Amenities nearby</th>
              <th scope="col">Green nearby</th>
              {FLAGS.map((flag) => (
                <th key={flag.key} scope="col">
                  {flag.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((block) => (
              <tr key={block.block_label}>
                <th scope="row">{block.block_label}</th>
                <td
                  className="is-count"
                  style={{ background: shade(block.nearby_amenities.length, maxAmenities) }}
                  title={block.nearby_amenities.join(", ") || "No amenities within the proximity radius"}
                >
                  {fmt(block.nearby_amenities.length)}
                </td>
                <td
                  className="is-count"
                  style={{ background: shade(block.nearby_green.length, maxGreen) }}
                  title={block.nearby_green.join(", ") || "No green space within the proximity radius"}
                >
                  {fmt(block.nearby_green.length)}
                </td>
                {FLAGS.map((flag) => {
                  const on = Boolean(block[flag.key]);
                  return (
                    <td key={flag.key} className={`is-flag${on ? "" : " is-off"}`}>
                      {on ? (
                        <>
                          <Check size={14} aria-hidden="true" /> near
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="viz-legend">
        <span>
          <span className="viz-key is-open" /> Darker cells have more nearby. Hover a count for the names.
        </span>
        {collapsible && (
          <button type="button" className="link-button" onClick={() => setExpanded((open) => !open)}>
            {expanded ? "Show fewer blocks" : `Show all ${fmt(sorted.length)} blocks`}
          </button>
        )}
      </p>
    </section>
  );
}
