const ORDER = [
  ['received', 'Received'],
  ['extracting', 'Extract text'],
  ['generating', 'Generate layer'],
  ['tracing', 'Trace artwork'],
  ['composing', 'Compose page'],
  ['building', 'Build site'],
  ['verifying', 'Verify'],
  ['packaging', 'Package'],
];

export default function Stepper({ job, onReset }) {
  const current = ORDER.findIndex(([k]) => k === job.stage);

  return (
    <div className="card">
      <div className="row between">
        <h2>{job.message}</h2>
        <span className="pct">{Math.round((job.progress || 0) * 100)}%</span>
      </div>

      <div className="bar">
        <div className="fill" style={{ width: `${(job.progress || 0) * 100}%` }} />
      </div>

      <ol className="steps">
        {ORDER.map(([key, label], i) => (
          <li
            key={key}
            className={
              i < current ? 'done' : i === current ? 'active' : 'todo'
            }
          >
            <span className="dot" />
            {label}
          </li>
        ))}
      </ol>

      {job.logs?.length > 0 && (
        <details className="logbox">
          <summary>Log</summary>
          <pre className="logs">{job.logs.slice(-40).join('\n')}</pre>
        </details>
      )}

      <p className="hint">
        Tracing the artwork and building the Astro site can take a few minutes.
      </p>
      <button className="ghost" onClick={onReset}>
        Cancel view
      </button>
    </div>
  );
}
