const STATUSES = ['draft', 'pass', 'fail', 'blocked'];

const $ = (sel) => document.querySelector(sel);
const form = $('#test-form');
const listEl = $('#list');
const statsEl = $('#stats');
const errorEl = $('#error');

let tests = [];
let stats = { total: 0, byStatus: { draft: 0, pass: 0, fail: 0, blocked: 0 }, passRate: null };
let editingId = null;
let searchTimer = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.classList.remove('hidden');
}

function clearError() {
  errorEl.textContent = '';
  errorEl.classList.add('hidden');
}

async function api(url, options = {}) {
  let res;
  try {
    res = await fetch(url, {
      ...options,
      headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    });
  } catch {
    throw new Error('Network error — is the server running?');
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

async function refresh() {
  try {
    const params = new URLSearchParams();
    const status = $('#filter-status').value;
    const q = $('#filter-q').value.trim();
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    const query = params.toString();
    const [testList, statsData] = await Promise.all([
      api(`/api/tests${query ? `?${query}` : ''}`),
      api('/api/stats'),
    ]);
    tests = testList;
    stats = statsData;
    clearError();
    render();
  } catch (err) {
    showError(err.message);
  }
}

function render() {
  renderStats();
  renderList();
}

function renderStats() {
  const rate = stats.passRate === null ? '—' : `${stats.passRate}%`;
  statsEl.innerHTML = `
    <span class="stat"><b>${stats.total}</b> total</span>
    <span class="stat"><b>${stats.byStatus.pass}</b> pass</span>
    <span class="stat"><b>${stats.byStatus.fail}</b> fail</span>
    <span class="stat"><b>${stats.byStatus.blocked}</b> blocked</span>
    <span class="stat"><b>${stats.byStatus.draft}</b> draft</span>
    <span class="stat"><b>${rate}</b> pass rate</span>`;
}

function renderList() {
  if (tests.length === 0) {
    listEl.innerHTML = '<p class="empty">No test cases found. Add your first one above.</p>';
    return;
  }
  listEl.innerHTML = tests.map((t) => `
    <article class="test-card" data-id="${escapeHtml(t.id)}">
      <div class="test-main">
        <div class="test-head">
          <span class="badge status-${escapeHtml(t.status)}">${escapeHtml(t.status)}</span>
          <span class="badge priority">${escapeHtml(t.priority)}</span>
          <h3>${escapeHtml(t.title)}</h3>
        </div>
        ${t.description ? `<p class="test-desc">${escapeHtml(t.description)}</p>` : ''}
        ${t.steps ? `
          <details>
            <summary>Steps</summary>
            <pre>${escapeHtml(t.steps)}</pre>
          </details>` : ''}
        <p class="test-meta">Updated ${escapeHtml(new Date(t.updatedAt).toLocaleString())}</p>
      </div>
      <div class="test-actions">
        ${STATUSES.filter((s) => s !== t.status).map(
          (s) => `<button class="btn btn-small" data-action="status" data-status="${s}">${cap(s)}</button>`
        ).join('')}
        <button class="btn btn-small" data-action="edit">Edit</button>
        <button class="btn btn-small btn-danger" data-action="delete">Delete</button>
      </div>
    </article>`).join('');
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

listEl.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const id = button.closest('.test-card').dataset.id;
  try {
    if (button.dataset.action === 'status') {
      await api(`/api/tests/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: button.dataset.status }),
      });
      await refresh();
    } else if (button.dataset.action === 'delete') {
      if (confirm('Delete this test case?')) {
        await api(`/api/tests/${id}`, { method: 'DELETE' });
        if (editingId === id) resetForm();
        await refresh();
      }
    } else if (button.dataset.action === 'edit') {
      const test = tests.find((t) => t.id === id);
      if (test) startEdit(test);
    }
  } catch (err) {
    showError(err.message);
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    title: $('#title').value,
    description: $('#description').value,
    steps: $('#steps').value,
    priority: $('#priority').value,
    status: $('#status').value,
  };
  try {
    if (editingId) {
      await api(`/api/tests/${editingId}`, { method: 'PATCH', body: JSON.stringify(payload) });
    } else {
      await api('/api/tests', { method: 'POST', body: JSON.stringify(payload) });
    }
    resetForm();
    await refresh();
  } catch (err) {
    showError(err.message);
  }
});

function startEdit(test) {
  editingId = test.id;
  $('#title').value = test.title;
  $('#description').value = test.description || '';
  $('#steps').value = test.steps || '';
  $('#priority').value = test.priority;
  $('#status').value = test.status;
  $('#form-title').textContent = 'Edit test case';
  $('#submit-btn').textContent = 'Save changes';
  $('#cancel-edit').classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetForm() {
  editingId = null;
  form.reset();
  $('#form-title').textContent = 'New test case';
  $('#submit-btn').textContent = 'Add test case';
  $('#cancel-edit').classList.add('hidden');
}

$('#cancel-edit').addEventListener('click', resetForm);
$('#filter-status').addEventListener('change', refresh);
$('#filter-q').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refresh, 250);
});

refresh();
