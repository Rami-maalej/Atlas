import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Store } from './lib/store.js';
import { validateTestCase, ValidationError } from './lib/validate.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.resolve(__dirname, 'public');
const DATA_FILE = process.env.TESTLAB_DATA || path.join(__dirname, 'data', 'testcases.json');
const PORT = Number(process.env.PORT) || 3000;
const MAX_BODY_BYTES = 100 * 1024;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon',
};

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function sendError(res, statusCode, message) {
  sendJson(res, statusCode, { error: message });
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(Object.assign(new Error('Request body too large'), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

async function readJsonBody(req) {
  const raw = await readBody(req);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw Object.assign(new Error('Invalid JSON body'), { statusCode: 400 });
  }
}

async function handleApi(req, res, pathname, searchParams, store) {
  const segments = pathname.split('/').filter(Boolean);
  const rest = segments.slice(1);

  try {
    if (rest[0] === 'health' && req.method === 'GET') {
      return sendJson(res, 200, { status: 'ok' });
    }

    if (rest[0] === 'stats' && req.method === 'GET') {
      return sendJson(res, 200, store.stats());
    }

    if (rest[0] === 'tests') {
      if (rest.length === 1) {
        if (req.method === 'GET') {
          return sendJson(res, 200, store.list({
            status: searchParams.get('status') || undefined,
            q: searchParams.get('q') || undefined,
          }));
        }
        if (req.method === 'POST') {
          const body = await readJsonBody(req);
          const data = validateTestCase(body);
          const item = await store.create(data);
          return sendJson(res, 201, item);
        }
      } else if (rest.length === 2) {
        const id = rest[1];
        if (req.method === 'GET') {
          const item = store.get(id);
          if (!item) return sendError(res, 404, 'Test case not found');
          return sendJson(res, 200, item);
        }
        if (req.method === 'PUT' || req.method === 'PATCH') {
          const body = await readJsonBody(req);
          const data = validateTestCase(body, { partial: true });
          const item = await store.update(id, data);
          if (!item) return sendError(res, 404, 'Test case not found');
          return sendJson(res, 200, item);
        }
        if (req.method === 'DELETE') {
          const ok = await store.remove(id);
          if (!ok) return sendError(res, 404, 'Test case not found');
          return sendJson(res, 200, { ok: true });
        }
      }
    }

    return sendError(res, 404, 'Not found');
  } catch (err) {
    if (err instanceof ValidationError) return sendError(res, 400, err.message);
    const status = err.statusCode || 500;
    if (status === 500) console.error(err);
    return sendError(res, status, status === 500 ? 'Internal server error' : err.message);
  }
}

async function serveStatic(res, pathname) {
  try {
    const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    const filePath = path.resolve(PUBLIC_DIR, rel);
    if (filePath !== PUBLIC_DIR && !filePath.startsWith(PUBLIC_DIR + path.sep)) {
      return sendError(res, 403, 'Forbidden');
    }
    const data = await fs.readFile(filePath);
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  } catch (err) {
    if (err.code === 'ENOENT' || err.code === 'EISDIR') {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
    } else {
      throw err;
    }
  }
}

export function createApp({ dataFile = DATA_FILE } = {}) {
  const store = new Store(dataFile);
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      const pathname = decodeURIComponent(url.pathname);
      await store.init();
      if (pathname === '/api' || pathname.startsWith('/api/')) {
        await handleApi(req, res, pathname, url.searchParams, store);
      } else if (req.method === 'GET' || req.method === 'HEAD') {
        await serveStatic(res, pathname);
      } else {
        sendError(res, 405, 'Method not allowed');
      }
    } catch (err) {
      console.error(err);
      if (!res.headersSent) {
        sendError(res, 500, 'Internal server error');
      } else {
        res.end();
      }
    }
  });
  server.store = store;
  return server;
}

export function start() {
  const server = createApp();
  server.listen(PORT, () => {
    console.log(`TestLab running at http://localhost:${PORT}`);
    console.log(`Data file: ${DATA_FILE}`);
  });
  return server;
}

const isMain = Boolean(process.argv[1]) &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isMain) start();
