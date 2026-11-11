import { api } from '../api.js';
import { setState, getState } from '../store.js';
import {
  h,
  render,
  toast,
  confirmAction,
  errorBanner,
  emptyState,
  formatPercent,
  formatDate,
} from '../ui.js';

export async function dashboardView() {
  const root = document.querySelector('#app');
  setState({ loading: true, error: null });

  try {
    const { tests } = await api.listTests();
    setState({ tests, loading: false });
  } catch (error) {
    setState({ loading: false, error });
    render(root, errorBanner(error));
    return;
  }

  const { tests } = getState();
  const header = h(
    'div.page-head',
    {},
    h(
      'div',
      {},
      h('h1', {}, 'Tests'),
      h('p.sub', {}, `${tests.length} test${tests.length === 1 ? '' : 's'} in your library`),
    ),
    h('a.btn.btn-primary', { href: '#/tests/new' }, '+ New test'),
  );

  if (tests.length === 0) {
    render(
      root,
      header,
      emptyState(
        'No tests yet. Create your first one to get started.',
        h('a.btn.btn-primary', { href: '#/tests/new' }, 'Create a test'),
      ),
    );
    return;
  }

  const cards = tests.map((test) =>
    h(
      'article.card',
      {},
      h(
        'div.card-head',
        {},
        h('h2', {}, test.title),
        h('span.badge', {}, `${test.questionCount} Q`),
      ),
      test.description ? h('p.desc', {}, test.description) : null,
      h(
        'div.stats',
        {},
        stat('Attempts', test.attemptCount),
        stat('Avg score', test.avgPercent === null ? '—' : formatPercent(test.avgPercent)),
        stat('Pass mark', `${test.passPercent}%`),
      ),
      h(
        'div.card-actions',
        {},
        h('a.btn.btn-primary', { href: `#/tests/${test.id}/take` }, 'Take test'),
        h('a.btn', { href: `#/tests/${test.id}/edit` }, 'Edit'),
        h(
          'button.btn.btn-danger',
          {
            type: 'button',
            onClick: async () => {
              const ok = confirmAction(`Delete "${test.title}" and all of its results?`);
              if (!ok) return;
              try {
                await api.deleteTest(test.id);
                setState({ tests: getState().tests.filter((t) => t.id !== test.id) });
                toast('Test deleted', 'success');
                dashboardView();
              } catch (error) {
                toast(error.message, 'error');
              }
            },
          },
          'Delete',
        ),
      ),
    ),
  );

  render(root, header, h('div.grid', {}, cards));
}

function stat(label, value) {
  return h(
    'div.stat',
    {},
    h('span.stat-label', {}, label),
    h('span.stat-value', {}, String(value)),
  );
}
