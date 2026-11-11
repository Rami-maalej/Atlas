/** Minimal fetch wrapper: JSON in/out, uniform ApiError with field details. */

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'UNKNOWN', details = [] } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Cannot reach the server. Is TestHub running?', { code: 'NETWORK' });
  }

  if (res.status === 204) return null;

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* fall through to generic error below */
  }

  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(err.message ?? `Request failed (${res.status})`, {
      status: res.status,
      code: err.code ?? 'REQUEST_ERROR',
      details: err.details ?? [],
    });
  }
  return data;
}

export const api = {
  listTests: () => request('/api/tests'),
  getTest: (id) => request(`/api/tests/${id}`),
  getTakeableTest: (id) => request(`/api/tests/${id}/take`),
  createTest: (input) => request('/api/tests', { method: 'POST', body: input }),
  updateTest: (id, input) => request(`/api/tests/${id}`, { method: 'PUT', body: input }),
  deleteTest: (id) => request(`/api/tests/${id}`, { method: 'DELETE' }),
  submitAttempt: (testId, answers) =>
    request(`/api/tests/${testId}/attempts`, { method: 'POST', body: { answers } }),
  listAttempts: () => request('/api/attempts'),
  getAttempt: (id) => request(`/api/attempts/${id}`),
};
