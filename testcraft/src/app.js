import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import testsRouter from './routes/tests.js';
import attemptsRouter from './routes/attempts.js';
import { errorHandler, notFound } from './middleware/errors.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createApp() {
  const app = express();

  app.use(express.json({ limit: '256kb' }));

  app.use('/api/tests', testsRouter);
  app.use('/api/attempts', attemptsRouter);

  // Unknown API route → JSON 404 (not the SPA)
  app.use('/api', notFound);

  // Static frontend
  app.use(express.static(path.join(__dirname, '..', 'public')));

  // SPA fallback for non-API GETs
  app.get('/*splat', (req, res, next) => {
    if (req.method !== 'GET' || req.path.startsWith('/api')) return next();
    res.sendFile(path.join(__dirname, '..', 'public', 'index.html'));
  });

  app.use(errorHandler);

  return app;
}
