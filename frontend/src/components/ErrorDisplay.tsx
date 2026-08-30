export default function ErrorDisplay({ message }: { message: string }) {
  return (
    <div className="error-display">
      <span className="error-display__icon">!</span>
      <span>{message}</span>
    </div>
  );
}
