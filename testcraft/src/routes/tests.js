import { Router } from 'express';
import * as repo from '../repo.js';
import { testInputSchema, zodDetails } from '../lib/validation.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';

const router = Router();

function parseInput(body) {
  const parsed = testInputSchema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError(400, 'Validation failed', zodDetails(parsed.error));
  }
  return parsed.data;
}

// List tests (summary only)
router.get(
  '/',
  asyncHandler((_req, res) => {
    res.json({ tests: repo.listTests() });
  }),
);

// Create a test
router.post(
  '/',
  asyncHandler((req, res) => {
    const input = parseInput(req.body);
    const test = repo.createTest(input);
    res.status(201).json({ test });
  }),
);

// Get one test. ?includeAnswers=false hides correct answers (used by the take view).
router.get(
  '/:id',
  asyncHandler((req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) throw new ApiError(400, 'Invalid test id');
    const includeAnswers = req.query.includeAnswers !== 'false';
    res.json({ test: repo.getTest(id, { withAnswers: includeAnswers }) });
  }),
);

// Update a test (resets its attempt history)
router.put(
  '/:id',
  asyncHandler((req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) throw new ApiError(400, 'Invalid test id');
    const input = parseInput(req.body);
    res.json({ test: repo.updateTest(id, input) });
  }),
);

// Delete a test (cascades questions and attempts)
router.delete(
  '/:id',
  asyncHandler((req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) throw new ApiError(400, 'Invalid test id');
    res.json(repo.deleteTest(id));
  }),
);

// Attempt history for a test
router.get(
  '/:id/attempts',
  asyncHandler((req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) throw new ApiError(400, 'Invalid test id');
    res.json({ attempts: repo.listAttempts(id) });
  }),
);

export default router;
