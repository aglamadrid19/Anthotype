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
