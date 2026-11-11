import { z } from 'zod';

const choiceSchema = z.object({
  id: z.number().int().positive().optional(),
  text: z.string().trim().min(1, 'Choice text cannot be empty').max(500),
  isCorrect: z.boolean(),
});

const questionSchema = z.object({
  id: z.number().int().positive().optional(),
  prompt: z.string().trim().min(1, 'Question prompt cannot be empty').max(2000),
  points: z.number().int().min(1).max(100).default(1),
  choices: z
    .array(choiceSchema)
    .min(2, 'Each question needs at least 2 choices')
    .max(8, 'A question can have at most 8 choices')
    .refine((choices) => choices.filter((c) => c.isCorrect).length === 1, {
      message: 'Each question must have exactly one correct choice',
    }),
});

export const testInputSchema = z
  .object({
    title: z.string().trim().min(1, 'Title cannot be empty').max(200),
    description: z.string().trim().max(2000).default(''),
    passPercent: z.number().int().min(0).max(100).default(60),
    shuffle: z.boolean().default(false),
    questions: z
      .array(questionSchema)
      .min(1, 'A test needs at least one question')
      .max(50, 'A test can have at most 50 questions'),
  })
  .strict();

export const attemptInputSchema = z
  .object({
    answers: z
      .array(
        z.object({
          questionId: z.number().int().positive(),
          choiceId: z.number().int().positive().nullable(),
        }),
      )
      .min(1),
  })
  .strict();

export const idParamSchema = z.coerce.number().int().positive();
