interface RiskBarProps {
  score: number | null;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

function getRiskColor(score: number): string {
  if (score >= 70) return "#ef4444";
  if (score >= 50) return "#f97316";
  if (score >= 30) return "#eab308";
  return "#22c55e";
}

function getRiskLabel(score: number): string {
  if (score >= 70) return "CRIT";
  if (score >= 50) return "HIGH";
  if (score >= 30) return "MED";
  return "LOW";
}

export default function RiskBar({
  score,
  size = "md",
  showLabel = true,
}: RiskBarProps) {
  if (score === null) {
    return (
      <div className={`risk-bar risk-bar--${size}`}>
        <div className="risk-bar__track">
          <div className="risk-bar__fill risk-bar__fill--pending" />
        </div>
        {showLabel && <span className="risk-bar__label risk-bar__label--pending">PEND</span>}
      </div>
    );
  }

  return (
    <div className={`risk-bar risk-bar--${size}`}>
      <div className="risk-bar__track">
        <div
          className="risk-bar__fill"
          style={{
            width: `${score}%`,
            backgroundColor: getRiskColor(score),
          }}
        />
      </div>
      {showLabel && (
        <span
          className="risk-bar__label"
          style={{ color: getRiskColor(score) }}
        >
          {getRiskLabel(score)} {score}
        </span>
      )}
    </div>
  );
}
