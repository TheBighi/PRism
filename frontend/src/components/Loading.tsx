export default function Loading({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="loading">
      <div className="loading__spinner" />
      <span>{text}</span>
    </div>
  );
}
