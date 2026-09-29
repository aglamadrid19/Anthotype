import { useState } from 'react';
import { downloadUrl, previewUrl, refUrl } from './api.js';

export default function Result({ job, onReset }) {
  const [view, setView] = useState('preview'); // preview | reference
  const score = job.score;
  const grade =
    score == null ? null : score < 3 ? 'good' : score < 6 ? 'ok' : 'rough';

  return (
    <div className="result">
      <div className="card">
        <div className="row between wrap">
          <div>
            <h2>Your site is ready</h2>
            <p className="hint">
              One self-contained <code>index.html</code> plus the full Astro
              project.
            </p>
          </div>
          <div className="actions">
            <a className="primary" href={downloadUrl(job.id)}>
              Download project
            </a>
            <button className="ghost" onClick={onReset}>
              New design
            </button>
          </div>
        </div>

        <div className="stats">
          <div className="stat">
            <span className="label">Fidelity</span>
            <span className={`value ${grade || ''}`}>
              {score == null ? 'n/a' : score.toFixed(2)}
            </span>
            <span className="unit">mean abs diff, lower is better</span>
          </div>
          <div className="stat">
            <span className="label">Pixels off &gt;30</span>
            <span className="value">
              {job.pct_over_30 == null ? 'n/a' : `${job.pct_over_30.toFixed(2)}%`}
            </span>
            <span className="unit">of the 1024×768 stage</span>
          </div>
          <div className="stat">
            <span className="label">Source</span>
            <span className="value small">
              {job.src?.width}×{job.src?.height}
            </span>
            <span className="unit">normalized to 1024×768</span>
          </div>
          <div className="stat">
            <span className="label">Page size</span>
            <span className="value small">
              {job.artifacts?.page_bytes
                ? `${Math.round(job.artifacts.page_bytes / 1024)} KB`
                : '—'}
            </span>
            <span className="unit">single file, zero requests</span>
          </div>
        </div>

        {job.warnings?.length > 0 && (
          <ul className="warnings">
            {job.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <div className="row between">
          <div className="tabs">
            <button
              className={view === 'preview' ? 'tab active' : 'tab'}
              onClick={() => setView('preview')}
            >
              Built site
            </button>
            <button
              className={view === 'reference' ? 'tab active' : 'tab'}
              onClick={() => setView('reference')}
            >
              Reference
            </button>
          </div>
          <a className="ghost small" href={previewUrl(job.id)} target="_blank" rel="noreferrer">
            Open in new tab ↗
          </a>
        </div>
        <div className="stage-frame">
          <iframe
            title={view}
            src={view === 'preview' ? previewUrl(job.id) : refUrl(job.id)}
            sandbox={view === 'preview' ? 'allow-scripts allow-same-origin' : ''}
          />
        </div>
      </div>

      {job.blocks?.length > 0 && (
        <div className="card">
          <h2>Extracted text layer</h2>
          <p className="hint">
            These are real DOM elements in the output, not baked into the artwork.
          </p>
          <table className="blocks">
            <thead>
              <tr>
                <th>Role</th>
                <th>Text</th>
                <th>Box</th>
                <th>Colour</th>
              </tr>
            </thead>
            <tbody>
              {job.blocks.map((b, i) => (
                <tr key={i}>
                  <td>
                    <span className={`role role-${b.role}`}>{b.role}</span>
                  </td>
                  <td className="text">{b.text}</td>
                  <td className="mono">{b.bbox.join(', ')}</td>
                  <td>
                    {b.color && (
                      <span className="swatch-wrap">
                        <span
                          className="swatch"
                          style={{ background: `rgb(${b.color.join(',')})` }}
                        />
                        <span className="mono">
                          {b.color.join(',')}
                        </span>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
