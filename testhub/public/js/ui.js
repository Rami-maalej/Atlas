/** DOM helpers: element builder, escaping, toasts, confirmations. */

export function h(tag, attrs = {}, ...children) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');

  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'value') {
      el.value = value;
    } else if (key === 'checked') {
      el.checked = Boolean(value);
    } else if (key === 'disabled') {
      el.disabled = Boolean(value);
    } else {
      el.setAttribute(key, value === true ? '' : String(value));
    }
  }

  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function render(node, ...children) {
  clear(node);
  node.append(...children.flat(Infinity).filter(Boolean));
}

export function toast(message, type = 'info', ms = 3200) {
  const box = document.querySelector('#toasts');
  const item = h(`div.toast.toast-${type}`, {}, message);
  box.append(item);
  setTimeout(() => {
    item.classList.add('toast-out');
    setTimeout(() => item.remove(), 300);
  }, ms);
}

/** Returns a promise-like confirmation using the native dialog. */
export function confirmAction(message) {
  return window.confirm(message);
}

export function errorBanner(error) {
  const details = (error?.details ?? [])
    .map((d) => h('li', {}, `${d.path || 'body'}: ${d.message}`));
  return h(
    'div.banner.banner-error',
    {},
    h('strong', {}, error?.message ?? 'Something went wrong'),
    details.length ? h('ul', {}, details) : null,
  );
}

export function emptyState(text, action) {
  return h('div.empty', {}, h('p', {}, text), action ?? null);
}

export function percentBadge(percent) {
  const cls = percent >= 70 ? 'ok' : percent >= 50 ? 'warn' : 'bad';
  return h(`span.badge.${cls}`, {}, `${formatPercent(percent)}`);
}

export function formatPercent(value) {
  const n = Number(value ?? 0);
  return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
}

export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z'));
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
