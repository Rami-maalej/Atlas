/** Tiny observable store — the app's single source of truth. */

const state = {
  tests: [],
  attempts: [],
  loading: false,
  error: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function clearError() {
  if (state.error) setState({ error: null });
}
