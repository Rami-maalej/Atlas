import { Router } from 'express';
import { getDb } from '../db.js';
import * as repo from '../repo.js';
import { attemptInputSchema, idParamSchema } from '../lib/validation.js';
import { asyncHandler, httpError } from '../middleware/errors.js';

const router = Router();

/** Submit an attempt for a test. */
router.post(
  '/tests/:id/attempts',
  asyncHandler((req, res) => {
    const testId = idParamSchema.parse(req.params.id);
    const input = attemptInputSchema.parse(req.body);
    const attempt = repo.createAttempt(getDb(), testId, input);
    if (!attempt) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    res.status(201).json({ attempt });
  }),
);

router.get(
  '/tests/:id/attempts',
  asyncHandler((req, res) => {
    const testId = idParamSchema.parse(req.params.id);
    if (!repo.getTest(getDb(), testId)) throw httpError(404, 'Test not found', 'TEST_NOT_FOUND');
    const all = repo.listAttempts(getDb()).filter((a) => a.testId === testId);
    res.json({ attempts: all });
  }),
);

router.get(
  '/attempts',
  asyncHandler((req, res) => {
    res.json({ attempts: repo.listAttempts(getDb()) });
  }),
);

router.get(
  '/attempts/:id',
  asyncHandler((req, res) => {
    const id = idParamSchema.parse(req.params.id);
    const attempt = repo.getAttempt(getDb(), id);
    if (!attempt) throw httpError(404, 'Attempt not found', 'ATTEMPT_NOT_FOUND');
    res.json({ attempt });
  }),
);

export default router;
