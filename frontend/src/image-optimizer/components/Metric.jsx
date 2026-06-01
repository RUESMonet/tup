export function Metric({ label, value }) {
  return (
    <div className="metric-item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
