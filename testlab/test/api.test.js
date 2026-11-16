import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createApp } from '../server.js';

let server;
let baseUrl;
let dataDir;

before(async () => {
  dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'testlab-api-'));
  server = createApp({ dataFile: path.join(dataDir, 'tests.json') });
  await new Promise((resolve) => server.listen(0, resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await fs.rm(dataDir, { recursive: true, force: true });
});

test('GET /api/health returns ok', async () => {
  const res = await fetch(`${baseUrl}/api/health`);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { status: 'ok' });
});

test('full CRUD lifecycle over /api/tests', async () => {
  const create = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: 'Search returns results',
      description: 'Verify search endpoint',
      steps: '1. Call API\n2. Check response',
      priority: 'high',
    }),
  });
  assert.equal(create.status, 201);
  const item = await create.json();
  assert.equal(item.title, 'Search returns results');
  assert.equal(item.priority, 'high');
  assert.equal(item.status, 'draft');

  const list = await fetch(`${baseUrl}/api/tests`);
  assert.equal(list.status, 200);
  assert.equal((await list.json()).length, 1);

  const patched = await fetch(`${baseUrl}/api/tests/${item.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'pass' }),
  });
  assert.equal(patched.status, 200);
  assert.equal((await patched.json()).status, 'pass');

  const getOne = await fetch(`${baseUrl}/api/tests/${item.id}`);
  assert.equal(getOne.status, 200);

  const remove = await fetch(`${baseUrl}/api/tests/${item.id}`, { method: 'DELETE' });
  assert.equal(remove.status, 200);

  const afterDelete = await fetch(`${baseUrl}/api/tests/${item.id}`);
  assert.equal(afterDelete.status, 404);
});

test('POST with missing title returns 400', async () => {
  const res = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description: 'no title' }),
  });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.error, /title/);
});

test('POST with invalid status returns 400', async () => {
  const res = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'X', status: 'banana' }),
  });
  assert.equal(res.status, 400);
});

test('POST with malformed JSON returns 400', async () => {
  const res = await fetch(`${baseUrl}/api/tests`, { method: 'POST', body: '{oops' });
  assert.equal(res.status, 400);
});

test('non-object JSON body returns 400', async () => {
  const res = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(['not', 'an', 'object']),
  });
  assert.equal(res.status, 400);
});

test('GET unknown id returns 404', async () => {
  const res = await fetch(`${baseUrl}/api/tests/does-not-exist`);
  assert.equal(res.status, 404);
});

test('unknown API route returns 404 JSON', async () => {
  const res = await fetch(`${baseUrl}/api/nope`);
  assert.equal(res.status, 404);
  assert.ok((await res.json()).error);
});

test('GET /api/tests supports status and q filters', async () => {
  const a = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Alpha login check' }),
  }).then((r) => r.json());
  const b = await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Beta checkout check', status: 'fail' }),
  }).then((r) => r.json());

  const byStatus = await fetch(`${baseUrl}/api/tests?status=fail`).then((r) => r.json());
  assert.equal(byStatus.length, 1);
  assert.equal(byStatus[0].id, b.id);

  const byQuery = await fetch(`${baseUrl}/api/tests?q=alpha`).then((r) => r.json());
  assert.equal(byQuery.length, 1);
  assert.equal(byQuery[0].id, a.id);

  await fetch(`${baseUrl}/api/tests/${a.id}`, { method: 'DELETE' });
  await fetch(`${baseUrl}/api/tests/${b.id}`, { method: 'DELETE' });
});

test('GET /api/stats reflects current data', async () => {
  await fetch(`${baseUrl}/api/tests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'Stats test', status: 'pass' }),
  });
  const res = await fetch(`${baseUrl}/api/stats`);
  const stats = await res.json();
  assert.equal(res.status, 200);
  assert.equal(stats.byStatus.pass, 1);
  assert.equal(stats.passRate, 100);
});

test('static index page is served', async () => {
  const res = await fetch(baseUrl);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type'), /text\/html/);
  assert.match(await res.text(), /<html/i);
});

test('static path traversal is blocked', async () => {
  const res = await fetch(`${baseUrl}/..%2F..%2Fpackage.json`);
  assert.ok([403, 404].includes(res.status));
  const text = await res.text();
  assert.doesNotMatch(text, /"name"/);
});

test('POST to static route returns 405', async () => {
  const res = await fetch(baseUrl, { method: 'POST' });
  assert.equal(res.status, 405);
});
