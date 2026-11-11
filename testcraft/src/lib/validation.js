import { z } from 'zod';

const optionText = z
  .string()
  .trim()
  .min(1, 'Options cannot be empty')
  .max(300, 'Option too long (max 300 chars)');

export const questionSchema = z
  .object({
    prompt: z.string().trim().min(1, 'Question text is required').max(1000, 'Question too long'),
    options: z.array(optionText).min(2, 'At least 2 options are required').max(8, 'Max 8 options'),
    correctIndex: z.number().int().min(0, 'correctIndex out of range'),
  })
  .superRefine((q, ctx) => {
    if (q.correctIndex >= q.options.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'correctIndex must point at an existing option',
        path: ['correctIndex'],
      });
    }
    const unique = new Set(q.options.map((o) => o.toLowerCase()));
    if (unique.size !== q.options.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Options must be unique',
        path: ['options'],
      });
    }
  });

export const testInputSchema = z.object({
  title: z.string().trim().min(1, 'Title is required').max(200, 'Title too long (max 200 chars)'),
  description: z.string().trim().max(2000, 'Description too long').default(''),
  passMark: z.number().int().min(0).max(100).default(60),
  questions: z.array(questionSchema).min(1, 'Add at least one question').max(100, 'Max 100 questions'),
});

export const attemptInputSchema = z.object({
  testId: z.number().int().positive(),
  answers: z
    .array(
      z.object({
        questionId: z.number().int().positive(),
        chosenIndex: z.number().int().min(-1).nullable(),
      }),
    )
    .min(1, 'No answers submitted'),
  durationMs: z.number().int().min(0).max(24 * 60 * 60 * 1000).nullable().default(null),
});

/** Convert a ZodError into a flat { field: message } map. */
export function zodDetails(error) {
  const details = {};
  for (const issue of error.issues) {
    const key = issue.path.join('.') || '_';
    if (!details[key]) details[key] = issue.message;
  }
  return details;
}
