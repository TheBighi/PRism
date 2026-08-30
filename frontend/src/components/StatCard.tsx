interface StatCardProps {
  label: string;
  value: number | string;
  accent?: boolean;
}

export default function StatCard({ label, value, accent }: StatCardProps) {
  return (
    <div className={`stat-card ${accent ? "stat-card--accent" : ""}`}>
      <div className="stat-card__value">{value}</div>
      <div className="stat-card__label">{label}</div>
    </div>
  );
}
