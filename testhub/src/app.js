import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import testsRouter from './routes/tests.js';
import attemptsRouter from './routes/attempts.js';
import { errorHandler, notFound } from './middleware/errors.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createApp() {
  const app = express();

  app.disable('x-powered-by');
  app.use(express.json({ limit: '1mb' }));

  app.use('/api/tests', testsRouter);
  app.use('/api', attemptsRouter);

  app.use('/api', notFound);

  app.use(express.static(path.join(__dirname, '..', 'public')));

  app.get('*', (req, res, next) => {
    if (req.method !== 'GET') return next();
    res.sendFile(path.join(__dirname, '..', 'public', 'index.html'));
  });

  app.use(notFound);
  app.use(errorHandler);

  return app;
}
