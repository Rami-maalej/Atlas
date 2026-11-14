export const STATUSES = ['draft', 'pass', 'fail', 'blocked'];
export const PRIORITIES = ['low', 'medium', 'high'];

export class ValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ValidationError';
    this.statusCode = 400;
  }
}

function cleanString(value, { field, required = false, max = 500 }) {
  if (value === undefined || value === null) {
    if (required) throw new ValidationError(`${field} is required`);
    return '';
  }
  if (typeof value !== 'string') {
    throw new ValidationError(`${field} must be a string`);
  }
  const trimmed = value.trim();
  if (required && trimmed.length === 0) {
    throw new ValidationError(`${field} is required`);
  }
  if (trimmed.length > max) {
    throw new ValidationError(`${field} must be at most ${max} characters`);
  }
  return trimmed;
}

export function validateTestCase(input, { partial = false } = {}) {
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    throw new ValidationError('Body must be a JSON object');
  }

  const out = {};

  if (!partial || input.title !== undefined) {
    out.title = cleanString(input.title, { field: 'title', required: true, max: 200 });
  }
  if (!partial || input.description !== undefined) {
    out.description = cleanString(input.description, { field: 'description', max: 2000 });
  }
  if (!partial || input.steps !== undefined) {
    out.steps = cleanString(input.steps, { field: 'steps', max: 5000 });
  }
  if (!partial || input.status !== undefined) {
    const status = input.status === undefined || input.status === null || input.status === ''
      ? 'draft'
      : input.status;
    if (!STATUSES.includes(status)) {
      throw new ValidationError(`status must be one of: ${STATUSES.join(', ')}`);
    }
    out.status = status;
  }
  if (!partial || input.priority !== undefined) {
    const priority = input.priority === undefined || input.priority === null || input.priority === ''
      ? 'medium'
      : input.priority;
    if (!PRIORITIES.includes(priority)) {
      throw new ValidationError(`priority must be one of: ${PRIORITIES.join(', ')}`);
    }
    out.priority = priority;
  }

  return out;
}
