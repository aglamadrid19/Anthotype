import { useState } from 'react';
import { acceptEnhance, downloadUrl, enhanceUrl, previewUrl, refUrl } from './api.js';

const SECTION_LABEL = {
  header: 'Header', nav: 'Navigation', hero: 'Hero', features: 'Features',
  testimonials: 'Testimonials', pricing: 'Pricing', contact: 'Contact',
  footer: 'Footer', other: 'Section',
};

const fmt = (n) => (n == null ? '—' : n.toFixed(2));

export default function Result({ job, onReset, onUpdate }) {
  const [view, setView] = useState('preview'); // preview | reference
  const [width, setWidth] = useState('full');  // full | tablet | phone
  const [enhanceBusy, setEnhanceBusy] = useState(false);
  const [enhanceError, setEnhanceError] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const info = typeof job.structure === 'object' && job.structure !== null
    ? job.structure : {};
  const sections = info.sections || [];
  const issues = job.structure_issues || info.issues || [];
  // The runner's advisory notes: a hero asset below its 2x size, a label the
  // shipped artwork may have lost.  Structure issues are already in `issues`,
  // and the runner prefixes its copies of them with "structure: ".
  const warnings = (job.warnings || []).filter((w) => !w.startsWith('structure: '));
  const notes = [...warnings, ...issues];
  // "svg" (flat artwork, traced geometry) or "photographic" (a fixed-resolution
  // image export).  The SVG art master is produced either way.  The export is
  // not only for photographs: a flat design whose upload carries more resolution
  // than the 1024px stage also ships the image, because the traced SVG is bounded
  // by the stage and a full-bleed hero magnifies it on a wider screen.
  const heroKind = job.hero_kind;
  const heroReason = job.hero_reason;

  // Ship the opt-in enhancement candidate: the endpoint rebuilds the page
  // synchronously and returns the updated job.
  const accept = async () => {
    setEnhanceError('');
    setEnhanceBusy(true);
    try {
      onUpdate(await acceptEnhance(job.id, reviewed));
    } catch (e) {
      setEnhanceError(String(e.message || e));
    } finally {
      setEnhanceBusy(false);
    }
  };

  return (
    <div className="result">
      <div className="card">
        <div className="row between wrap">
          <div>
            <h2>{notes.length ? 'Your site is built — review the notes' : 'Your site is built'}</h2>
            <p className="hint">
              A responsive, semantic page in normal flow —{' '}
              <code>header</code>, <code>nav</code>, <code>section</code>s and a{' '}
              <code>footer</code> — plus the full Astro project.{' '}
              {heroKind === 'photographic'
                ? 'The hero backdrop is exported as a fixed-resolution image '
                : 'The traced artwork is the hero backdrop; '}{' '}
              the copy is real DOM.
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

        {notes.length > 0 && (
          <ul className="warnings">
            {notes.map((w, i) => (
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
            <span className="value small">
              {info.has_svg ? 'traced SVG' : info.has_art ? 'image export' : '—'}
            </span>
            <span className="unit">
              {heroKind === 'photographic'
                ? `${job.hero_enhance === 'accepted' ? 'enhanced · ' : ''}hero art ${fmt(job.hero_fidelity)}`
                : job.score == null
                  ? 'art fidelity —'
                  : `art fidelity ${job.score.toFixed(2)}`}
            </span>
          </div>
        </div>
        <p className="hint">
          {heroKind === 'photographic' ? (
            <>
              <strong>{fmt(job.hero_fidelity)}</strong> measures the{' '}
              <em>image the page ships</em> against the reference.{' '}
              {heroReason ? <>{heroReason[0].toUpperCase() + heroReason.slice(1)} — </> : null}
              {job.hero_layout === 'split'
                ? 'the illustration keeps the mockup’s own labels and is shown whole, so nothing is cropped or dimmed. '
                : 'the image is built from your upload at its own resolution, so a full-bleed hero stays sharp instead of magnifying the 1024px trace. '}
              <strong>{fmt(job.score)}</strong> is the traced SVG master, kept
              as a separate deliverable.
            </>
          ) : (
            <>
              <strong>{fmt(job.score)}</strong> measures the{' '}
              <em>traced artwork</em> (and the palette) against the reference —
              not the type. The page is authored in its own type scale, not a
              pixel copy of the mockup's typeface.
            </>
          )}
        </p>
      </div>

      {job.hero_enhance === 'diagnostic' && (
        <div className="card">
          <h2>Enhanced artwork is diagnostic only</h2>
          <p className="hint">
            The source-preserving repair could not verify every protected
            content region, so this candidate <strong>cannot be accepted</strong>.
            The cleaned-native artwork keeps shipping; the preview below is for
            inspection only.
            {job.hero_enhance_meta?.repair?.reason ? (
              <> Reason: <code>{job.hero_enhance_meta.repair.reason}</code>.</>
            ) : null}
          </p>
          <img
            className="enhance-preview"
            src={enhanceUrl(job.id)}
            alt="Diagnostic enhancement candidate, not acceptable"
          />
        </div>
      )}

      {job.hero_enhance === 'pending' && (
        <div className="card">
          <div className="row between wrap">
            <div>
              <h2>Enhanced artwork ready to review</h2>
              <p className="hint">
                A sharper high-resolution rendition from{' '}
                <code>{job.hero_enhance_meta?.model || 'the image model'}</code> is
                available but <strong>not shipped</strong>. It is a generative
                re-render, so compare it with the current build (small labels can
                change) before accepting. Accepting rebuilds the page around it;
                LaMa/Lanczos stays the fallback until then.
                {job.hero_enhance_meta?.repair?.version ? (
                  <>
                    {' '}
                    A <strong>source-preserving repair</strong> restored{' '}
                    {job.hero_enhance_meta.repair.audit?.repaired ?? 'the'}{' '}
                    protected content region(s) from your native artwork; the
                    candidate below is the repaired rendition.
                  </>
                ) : null}
              </p>
            </div>
            <div className="actions">
              <button
                className="primary"
                onClick={accept}
                disabled={enhanceBusy || !reviewed}
              >
                {enhanceBusy ? 'Rebuilding…' : 'Accept enhanced artwork'}
              </button>
            </div>
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            I compared the candidate with the current build and its labels are
            intact. Accepting rebuilds the page; the review is recorded against
            this candidate.
          </label>
          {enhanceError && <p className="hint warn">{enhanceError}</p>}
          <img
            className="enhance-preview"
            src={enhanceUrl(job.id)}
            alt="Enhanced artwork candidate, not yet shipped"
          />
        </div>
      )}

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
            src={view === 'preview'
              ? `${previewUrl(job.id)}?v=${job.updated || ''}`
              : refUrl(job.id)}
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
