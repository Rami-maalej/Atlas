import { ZodError } from 'zod';

export function notFound(req, res) {
  res.status(404).json({ error: { message: `Route not found: ${req.method} ${req.originalUrl}` } });
}

export function errorHandler(err, req, res, next) {
  if (res.headersSent) return next(err);

  if (err instanceof ZodError) {
    return res.status(400).json({
      error: {
        message: 'Validation failed',
        code: 'VALIDATION_ERROR',
        details: err.issues.map((i) => ({ path: i.path.join('.'), message: i.message })),
      },
    });
  }

  if (err?.type === 'entity.parse.failed') {
    return res.status(400).json({
      error: { message: 'Malformed JSON in request body', code: 'BAD_JSON' },
    });
  }

  if (err?.status) {
    return res.status(err.status).json({
      error: { message: err.message, code: err.code ?? 'REQUEST_ERROR' },
    });
  }

  console.error(`[testhub] ${req.method} ${req.originalUrl} ->`, err);
  res.status(500).json({ error: { message: 'Internal server error', code: 'INTERNAL' } });
}

/** Wraps async route handlers so rejections reach the error middleware. */
export const asyncHandler = (fn) => (req, res, next) => {
  Promise.resolve(fn(req, res, next)).catch(next);
};

export function httpError(status, message, code) {
  const err = new Error(message);
  err.status = status;
  err.code = code;
  return err;
}
