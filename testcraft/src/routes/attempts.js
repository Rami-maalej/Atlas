import { Router } from 'express';
import * as repo from '../repo.js';
import { scoreAttempt } from '../lib/scoring.js';
import { attemptInputSchema, zodDetails } from '../lib/validation.js';
import { ApiError, asyncHandler } from '../middleware/errors.js';

const router = Router();

// Submit answers for a test → server-side scoring
router.post(
  '/',
  asyncHandler((req, res) => {
    const parsed = attemptInputSchema.safeParse(req.body);
    if (!parsed.success) {
      throw new ApiError(400, 'Validation failed', zodDetails(parsed.error));
    }
    const { testId, answers, durationMs } = parsed.data;

    const test = repo.getTest(testId, { withAnswers: false });
    if (answers.length !== test.questions.length) {
      throw new ApiError(400, 'Answer count does not match question count', {
        expected: test.questions.length,
        received: answers.length,
      });
    }

    const normalized = repo.buildAnswers(test, answers);
    const result = scoreAttempt(normalized, test.passMark);

    const attempt = repo.saveAttempt({
      testId,
      score: result.score,
      correctCount: result.correctCount,
      total: result.total,
      passed: result.passed,
      durationMs,
      answers: normalized.map((a) => ({
        chosenIndex: a.chosen,
        isCorrect: a.chosen !== null && a.chosen === a.correct,
      })),
    });

    res.status(201).json({ attempt });
  }),
);

// Get a full attempt with per-question review
router.get(
  '/:id',
  asyncHandler((req, res) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) throw new ApiError(400, 'Invalid attempt id');
    res.json({ attempt: repo.getAttempt(id) });
  }),
);

export default router;
