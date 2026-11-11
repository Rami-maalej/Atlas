/** Hash router: maps `#/segment/param` to a handler. */

const routes = [];
let notFound = () => {};
let current = null;

export function route(pattern, handler) {
  const names = [];
  const regex = new RegExp(
    '^' +
      pattern
        .split('/')
        .map((seg) => {
          if (seg.startsWith(':')) {
            names.push(seg.slice(1));
            return '([^/]+)';
          }
          return seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        })
        .join('/') +
      '$',
  );
  routes.push({ regex, names, handler });
}

export function setNotFound(handler) {
  notFound = handler;
}

export function navigate(hash) {
  if (location.hash === hash) resolve();
  else location.hash = hash;
}

export function resolve() {
  const path = location.hash.replace(/^#/, '') || '/';
  for (const { regex, names, handler } of routes) {
    const match = path.match(regex);
    if (match) {
      const params = Object.fromEntries(names.map((n, i) => [n, decodeURIComponent(match[i + 1])]));
      current = { path, handler };
      handler(params);
      return;
    }
  }
  notFound(path);
}

export function startRouter() {
  window.addEventListener('hashchange', resolve);
  resolve();
}

export function currentPath() {
  return current?.path ?? '/';
}
