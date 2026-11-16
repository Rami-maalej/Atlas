import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

export class Store {
  constructor(filePath) {
    this.filePath = filePath;
    this.items = [];
    this.loaded = false;
  }

  async init() {
    if (this.loaded) return this;
    try {
      const raw = await fs.readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw);
      this.items = Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
      this.items = [];
      await this.persist();
    }
    this.loaded = true;
    return this;
  }

  async persist() {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    const tmp = `${this.filePath}.tmp`;
    await fs.writeFile(tmp, JSON.stringify(this.items, null, 2), 'utf8');
    await fs.rename(tmp, this.filePath);
  }

  list({ status, q } = {}) {
    let result = this.items;
    if (status) {
      result = result.filter((t) => t.status === status);
    }
    if (q) {
      const needle = q.toLowerCase();
      result = result.filter((t) =>
        [t.title, t.description].some(
          (v) => typeof v === 'string' && v.toLowerCase().includes(needle)
        )
      );
    }
    return [...result].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''));
  }

  get(id) {
    return this.items.find((t) => t.id === id) || null;
  }

  async create(data) {
    const now = new Date().toISOString();
    const item = {
      id: crypto.randomUUID(),
      title: typeof data.title === 'string' ? data.title.trim() : data.title,
      description: data.description || '',
      steps: data.steps || '',
      status: data.status || 'draft',
      priority: data.priority || 'medium',
      createdAt: now,
      updatedAt: now,
    };
    this.items.push(item);
    await this.persist();
    return item;
  }

  async update(id, data) {
    const item = this.get(id);
    if (!item) return null;
    Object.assign(item, data, { updatedAt: new Date().toISOString() });
    await this.persist();
    return item;
  }

  async remove(id) {
    const index = this.items.findIndex((t) => t.id === id);
    if (index === -1) return false;
    this.items.splice(index, 1);
    await this.persist();
    return true;
  }

  stats() {
    const byStatus = { draft: 0, pass: 0, fail: 0, blocked: 0 };
    for (const t of this.items) {
      if (byStatus[t.status] !== undefined) byStatus[t.status] += 1;
    }
    const total = this.items.length;
    const done = byStatus.pass + byStatus.fail;
    return {
      total,
      byStatus,
      passRate: done === 0 ? null : Math.round((byStatus.pass / done) * 100),
    };
  }
}
