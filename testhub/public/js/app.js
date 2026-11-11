import { startRouter, route, setNotFound } from './router.js';
import { h, render } from './ui.js';
import { dashboardView } from './views/dashboard.js';
import { editorView } from './views/editor.js';
import { takeView, historyView, resultView } from './views/take.js';

route('/', dashboardView);
route('/history', historyView);
route('/tests/new', () => editorView({}));
route('/tests/:id/edit', editorView);
route('/tests/:id/take', takeView);
route('/attempts/:id', resultView);

setNotFound((path) => {
  render(
    document.querySelector('#app'),
    h('div.empty', {}, h('h1', {}, '404'), h('p', {}, `No page at #${path}`), h('a.btn', { href: '#/' }, 'Go home')),
  );
});

function highlightNav() {
  const path = location.hash.replace(/^#/, '') || '/';
  document.querySelectorAll('nav a[data-nav]').forEach((a) => {
    const key = a.dataset.nav;
    const active =
      (key === 'dashboard' && (path === '/' || path.startsWith('/tests'))) ||
      (key === 'history' && path.startsWith('/history'));
    a.classList.toggle('active', active);
  });
}

window.addEventListener('hashchange', highlightNav);
highlightNav();
startRouter();
