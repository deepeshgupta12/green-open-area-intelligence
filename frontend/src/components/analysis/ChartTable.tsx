type ChartTableProps = {
  caption: string;
  columns: string[];
  rows: Array<Array<string | number>>;
};

/** The WCAG twin of every chart: the same numbers as a plain table. */
export function ChartTable({ caption, columns, rows }: ChartTableProps) {
  return (
    <div className="chart-table-wrap">
      <table className="chart-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ViewToggleProps = {
  view: "chart" | "table";
  onChange: (view: "chart" | "table") => void;
};

export function ViewToggle({ view, onChange }: ViewToggleProps) {
  return (
    <div className="view-toggle" role="group" aria-label="Chart or table view">
      <button type="button" className={view === "chart" ? "is-active" : ""} onClick={() => onChange("chart")}>
        Chart
      </button>
      <button type="button" className={view === "table" ? "is-active" : ""} onClick={() => onChange("table")}>
        Table
      </button>
    </div>
  );
}
