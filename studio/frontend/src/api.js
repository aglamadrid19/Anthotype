// Thin API client. The Vite dev server proxies /api to the FastAPI backend.
const json = async (r) => {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return r.json();
};

export const getHealth = () => fetch('/api/health').then(json);

export const createJob = (file) => {
  const body = new FormData();
  body.append('file', file);
  return fetch('/api/jobs', { method: 'POST', body }).then(json);
};

export const getJob = (id) => fetch(`/api/jobs/${id}`).then(json);

export const previewUrl = (id) => `/api/jobs/${id}/preview`;
export const refUrl = (id) => `/api/jobs/${id}/ref`;
export const downloadUrl = (id) => `/api/jobs/${id}/download`;
export const enhanceUrl = (id) => `/api/jobs/${id}/enhance`;

// Ship the opt-in enhancement candidate and rebuild the page.  `reviewed` is
// the explicit confirmation that the candidate's labels were checked against
// the build; the backend refuses to ship without it.  The call runs the build
// synchronously, so it can take a while.
export const acceptEnhance = (id, reviewed) =>
  fetch(`/api/jobs/${id}/enhance/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewed: !!reviewed }),
  }).then(json);
