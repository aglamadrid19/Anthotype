import { useEffect, useRef, useState } from 'react';
import { createJob, getHealth, getJob } from './api.js';
import Stepper from './Stepper.jsx';
import Result from './Result.jsx';

export default function App() {
  const [health, setHealth] = useState(null);
  const [file, setFile] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const poll = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e.message || e)));
  }, []);

  // Poll the active job until it reaches a terminal state.
  useEffect(() => {
    if (!job || ['done', 'failed'].includes(job.status)) return undefined;
    poll.current = setInterval(async () => {
      try {
        setJob(await getJob(job.id));
      } catch (e) {
        setError(String(e.message || e));
      }
    }, 1500);
    return () => clearInterval(poll.current);
  }, [job?.id, job?.status]);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setError('');
    setBusy(true);
    try {
      const { id } = await createJob(file);
      setJob(await getJob(id));
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setJob(null);
    setFile(null);
    setError('');
  };

  return (
    <div className="app">
      <header>
        <h1>
          Anthotype <span className="accent">Studio</span>
        </h1>
        <p className="sub">
          Upload a flat design PNG. Get back a real, code-native website — DOM
          text, CSS and traced SVG, no raster images in the output.
        </p>
      </header>

      {error && <div className="banner error">{error}</div>}

      {!job && (
        <form className="card upload" onSubmit={submit}>
          <label className={`drop ${file ? 'has' : ''}`}>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? (
              <span className="filename">{file.name}</span>
            ) : (
              <>
                <span className="drop-title">Drop a design PNG</span>
                <span className="drop-sub">or click to choose a file</span>
              </>
            )}
          </label>

          <button className="primary" type="submit" disabled={!file || busy}>
            {busy ? 'Starting…' : 'Generate site'}
          </button>

          {health && !health.vision.configured && health.vision.provider !== 'stub' && (
            <p className="hint warn">
              Vision model not configured — text extraction will fail. Set
              <code> VISION_MODEL</code> and <code>VISION_API_KEY</code> in
              <code> studio/backend/.env</code>.
            </p>
          )}
          {health && health.vision.provider === 'stub' && (
            <p className="hint">
              Running with the <code>stub</code> vision provider: the page will
              have no text layer (artwork only).
            </p>
          )}
        </form>
      )}

      {job && ['queued', 'running'].includes(job.status) && (
        <Stepper job={job} onReset={reset} />
      )}

      {job && job.status === 'failed' && (
        <div className="card">
          <h2 className="fail">Build failed</h2>
          <pre className="logs">{job.logs?.slice(-30).join('\n')}</pre>
          <p className="hint">{job.error}</p>
          <button className="primary" onClick={reset}>
            Try another design
          </button>
        </div>
      )}

      {job && job.status === 'done' && <Result job={job} onReset={reset} />}
    </div>
  );
}
