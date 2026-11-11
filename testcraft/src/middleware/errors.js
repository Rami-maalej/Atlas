export class ApiError extends Error {
  constructor(status, message, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export function notFound(req, res) {
  res.status(404).json({ error: 'Not found', details: { path: req.originalUrl } });
}

export function errorHandler(err, _req, res, _next) {
  if (err instanceof ApiError) {
    res.status(err.status).json({ error: err.message, details: err.details });
    return;
  }
  if (err?.type === 'entity.parse.failed') {
    res.status(400).json({ error: 'Malformed JSON body' });
    return;
  }
  console.error(err);
  res.status(500).json({ error: 'Internal server error' });
}

/** Wrap async route handlers so rejections reach the error handler (Express 5 does this natively,
 * but this keeps behavior explicit and safe if the framework changes). */
export function asyncHandler(fn) {
  return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);
}
