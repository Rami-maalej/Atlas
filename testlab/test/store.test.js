import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { Store } from '../lib/store.js';

let dir;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'testlab-'));
});

afterEach(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

test('create assigns id, defaults, and persists to disk', async () => {
  const file = path.join(dir, 'tests.json');
  const store = await new Store(file).init();
  const item = await store.create({ title: '  Login works  ' });

  assert.ok(item.id);
  assert.equal(item.title, 'Login works');
  assert.equal(item.status, 'draft');
  assert.equal(item.priority, 'medium');
  assert.equal(item.description, '');
  assert.ok(item.createdAt);
  assert.ok(item.updatedAt);

  const raw = JSON.parse(await fs.readFile(file, 'utf8'));
  assert.equal(raw.length, 1);
  assert.equal(raw[0].id, item.id);
});

test('get returns item by id and null for unknown id', async () => {
  const store = await new Store(path.join(dir, 'tests.json')).init();
  const item = await store.create({ title: 'A' });
  assert.equal(store.get(item.id).title, 'A');
  assert.equal(store.get('no-such-id'), null);
});

test('list filters by status and search query, newest first', async () => {
  const store = await new Store(path.join(dir, 'tests.json')).init();
  const first = await store.create({ title: 'Login test', description: 'auth flow' });
  await store.create({ title: 'Checkout test' });
  await store.update(first.id, { status: 'pass' });

  assert.equal(store.list().length, 3);
  assert.equal(store.list({ status: 'pass' }).length, 1);
  assert.equal(store.list({ q: 'checkout' }).length, 1);
  assert.equal(store.list({ q: 'auth' }).length, 1);
  assert.equal(store.list({ q: 'AUTH' }).length, 1);
  assert.equal(store.list()[0].title, 'Checkout test');
});

test('update changes fields and keeps id', async () => {
  const store = await new Store(path.join(dir, 'tests.json')).init();
  const item = await store.create({ title: 'A' });
  const updated = await store.update(item.id, { status: 'fail', title: 'A2' });

  assert.equal(updated.status, 'fail');
  assert.equal(updated.title, 'A2');
  assert.equal(updated.id, item.id);
  assert.equal(store.get(item.id).title, 'A2');
  assert.equal(await store.update('missing', { status: 'pass' }), null);
});

test('remove deletes item and reports missing ids', async () => {
  const store = await new Store(path.join(dir, 'tests.json')).init();
  const item = await store.create({ title: 'A' });

  assert.equal(await store.remove(item.id), true);
  assert.equal(store.list().length, 0);
  assert.equal(await store.remove(item.id), false);
});

test('stats aggregates counts and pass rate', async () => {
  const store = await new Store(path.join(dir, 'tests.json')).init();
  assert.deepEqual(store.stats(), {
    total: 0,
    byStatus: { draft: 0, pass: 0, fail: 0, blocked: 0 },
    passRate: null,
  });

  const a = await store.create({ title: 'A' });
  const b = await store.create({ title: 'B' });
  await store.create({ title: 'C' });
  await store.update(a.id, { status: 'pass' });
  await store.update(b.id, { status: 'fail' });

  const stats = store.stats();
  assert.equal(stats.total, 3);
  assert.equal(stats.byStatus.pass, 1);
  assert.equal(stats.byStatus.fail, 1);
  assert.equal(stats.byStatus.draft, 1);
  assert.equal(stats.passRate, 50);
});

test('store reloads persisted data in a new instance', async () => {
  const file = path.join(dir, 'tests.json');
  const store1 = await new Store(file).init();
  const item = await store1.create({ title: 'Durable' });

  const store2 = await new Store(file).init();
  assert.equal(store2.get(item.id).title, 'Durable');
});
