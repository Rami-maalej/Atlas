import { Router } from 'express';
import { getDb } from '../db.js';
import * as repo from '../repo.js';
import { testInputSchema, idParamSchema } from '../lib/validation.js';
import { asyncHandler, httpError } from '../middleware/errors.js';

const router = Router();

router.get(
  '/',
  asyncHandler((req, res) => {
    res.json({ tests: repo.listTests(getDb()) });
  }),
);

router.post(
  '/',
  asyncHandler((req, res) => {
    const input = testInputSchema.parse(req.body);
    const id = repo.createTest(getDb(), input);
    res.status(201).json({ test: repo.getTest(getDb(), id) });
  }),
);

router.get(
  '/:id',
  asyncHandler((req, res) => {
    const id = idParamSchema.parse(req.params.id);
    const test = repo.getTest(getDb(), id);
    if (!test) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    res.json({ test });
  }),
);

/** Same as above but never leaks which choice is correct. */
router.get(
  '/:id/take',
  asyncHandler((req, res) => {
    const id = idParamSchema.parse(req.params.id);
    const test = repo.getTest(getDb(), id, { includeAnswers: false });
    if (!test) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    res.json({ test });
  }),
);

router.put(
  '/:id',
  asyncHandler((req, res) => {
    const id = idParamSchema.parse(req.params.id);
    const input = testInputSchema.parse(req.body);
    const updated = repo.updateTest(getDb(), id, input);
    if (!updated) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    res.json({ test: repo.getTest(getDb(), id) });
  }),
);

router.delete(
  '/:id',
  asyncHandler((req, res) => {
    const id = idParamSchema.parse(req.params.id);
    const deleted = repo.deleteTest(getDb(), id);
    if (!deleted) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    res.status(204).end();
  }),
);

export default router;
