import { useState } from 'react';
import { downloadUrl, previewUrl, refUrl } from './api.js';

const SECTION_LABEL = {
  header: 'Header', nav: 'Navigation', hero: 'Hero', features: 'Features',
  testimonials: 'Testimonials', pricing: 'Pricing', contact: 'Contact',
  footer: 'Footer', other: 'Section',
};

export default function Result({ job, onReset }) {
  const [view, setView] = useState('preview'); // preview | reference
  const [width, setWidth] = useState('full');  // full | tablet | phone
  const info = typeof job.structure === 'object' && job.structure !== null
    ? job.structure : {};
  const sections = info.sections || [];
  const issues = job.structure_issues || info.issues || [];

  return (
    <div className="result">
      <div className="card">
        <div className="row between wrap">
          <div>
            <h2>{issues.length ? 'Your site is built — review the notes' : 'Your site is built'}</h2>
            <p className="hint">
              A responsive, semantic page in normal flow —{' '}
              <code>header</code>, <code>nav</code>, <code>section</code>s and a{' '}
              <code>footer</code> — plus the full Astro project. The traced
              artwork is the hero backdrop; the copy is real DOM.
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

        {issues.length > 0 && (
          <ul className="warnings">
            {issues.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}

        <div className="stats">
          <div className="stat">
            <span className="label">Sections</span>
            <span className="value">{sections.length || (info.all_sections?.length ?? 0)}</span>
            <span className="unit">
              {sections.length
                ? [...new Set(sections)].map((s) => SECTION_LABEL[s] || s).join(' · ')
                : 'hero only'}
            </span>
          </div>
          <div className="stat">
            <span className="label">Headings</span>
            <span className="value small">
              {info.headings
                ? `h1×${info.headings.h1} h2×${info.headings.h2} h3×${info.headings.h3}`
                : '—'}
            </span>
            <span className="unit">one h1, ordered below it</span>
          </div>
          <div className="stat">
            <span className="label">Links</span>
            <span className="value">{info.links ?? '—'}</span>
            <span className="unit">
              {info.dead_links?.length ? `${info.dead_links.length} dead` : 'all resolve'}
            </span>
          </div>
          <div className="stat">
            <span className="label">Artwork</span>
            <span className="value small">{info.has_art ? 'traced' : '—'}</span>
            <span className="unit">
              {job.score == null
                ? 'art fidelity —'
                : `art fidelity ${job.score.toFixed(2)}`}
            </span>
          </div>
        </div>
        <p className="hint">
          <strong>Fidelity {job.score == null ? '—' : job.score.toFixed(2)}</strong>{' '}
          measures the <em>traced artwork</em> (and the palette) against the
          reference — not the type. The page is authored in its own type scale,
          not a pixel copy of the mockup's typeface.
        </p>
      </div>

      <div className="card">
        <div className="row between wrap">
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
          {view === 'preview' && (
            <div className="tabs">
              {['full', 'tablet', 'phone'].map((w) => (
                <button
                  key={w}
                  className={width === w ? 'tab active' : 'tab'}
                  onClick={() => setWidth(w)}
                >
                  {w === 'full' ? 'Desktop' : w === 'tablet' ? 'Tablet' : 'Phone'}
                </button>
              ))}
            </div>
          )}
          <a className="ghost small" href={previewUrl(job.id)} target="_blank" rel="noreferrer">
            Open in new tab ↗
          </a>
        </div>
        <div className={`stage-frame ${width}`}>
          <iframe
            title={view}
            src={view === 'preview' ? previewUrl(job.id) : refUrl(job.id)}
            sandbox={view === 'preview' ? 'allow-scripts allow-same-origin' : ''}
          />
        </div>
      </div>

      {job.blocks?.length > 0 && (
        <div className="card">
          <h2>Extracted content</h2>
          <p className="hint">
            Real DOM elements in the output, grouped into the page&apos;s sections
            — not baked into the artwork.
          </p>
          <table className="blocks">
            <thead>
              <tr>
                <th>Section</th>
                <th>Role</th>
                <th>Text</th>
                <th>Colour</th>
              </tr>
            </thead>
            <tbody>
              {job.blocks.map((b, i) => (
                <tr key={i}>
                  <td className="mono">{b.section || '—'}</td>
                  <td>
                    <span className={`role role-${b.role}`}>{b.role}</span>
                  </td>
                  <td className="text">{b.text}</td>
                  <td>
                    {b.color && (
                      <span className="swatch-wrap">
                        <span
                          className="swatch"
                          style={{ background: `rgb(${b.color.join(',')})` }}
                        />
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
