interface HealthCardProps {
  score: number;
  label?: string;
}

function getScoreColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 60) return "#eab308";
  if (score >= 40) return "#f97316";
  return "#ef4444";
}

export default function HealthCard({ score, label = "Health" }: HealthCardProps) {
  const circumference = 2 * Math.PI * 44;
  const offset = circumference - (score / 100) * circumference;
  const color = getScoreColor(score);

  return (
    <div className="health-card">
      <svg viewBox="0 0 100 100" className="health-card__ring">
        <circle
          cx="50"
          cy="50"
          r="44"
          fill="none"
          stroke="#27272a"
          strokeWidth="4"
        />
        <circle
          cx="50"
          cy="50"
          r="44"
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeDasharray={`${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="square"
          transform="rotate(-90 50 50)"
          className="health-card__ring-fill"
        />
        <text
          x="50"
          y="50"
          textAnchor="middle"
          dominantBaseline="central"
          className="health-card__score"
          fill={color}
        >
          {score}
        </text>
      </svg>
      <div className="health-card__label">{label}</div>
    </div>
  );
}
