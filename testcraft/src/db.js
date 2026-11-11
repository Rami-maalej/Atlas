import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const DATA_DIR = process.env.TESTCRAFT_DATA_DIR || path.join(__dirname, '..', 'data');
export const DB_PATH = process.env.TESTCRAFT_DB || path.join(DATA_DIR, 'testcraft.db');

fs.mkdirSync(DATA_DIR, { recursive: true });

export const db = new DatabaseSync(DB_PATH);

db.exec(`
  PRAGMA foreign_keys = ON;

  CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    pass_mark INTEGER NOT NULL DEFAULT 60,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    options TEXT NOT NULL,
    correct_index INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    correct_count INTEGER NOT NULL,
    total INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS attempt_answers (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL,
    chosen_index INTEGER,
    is_correct INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, question_id)
  );

  CREATE INDEX IF NOT EXISTS idx_questions_test ON questions(test_id, position);
  CREATE INDEX IF NOT EXISTS idx_attempts_test ON attempts(test_id, created_at);
`);

export function seedIfEmpty() {
  const row = db.prepare('SELECT COUNT(*) AS n FROM tests').get();
  if (row.n > 0) return;

  const insertTest = db.prepare(
    'INSERT INTO tests (title, description, pass_mark) VALUES (?, ?, ?)',
  );
  const insertQuestion = db.prepare(
    'INSERT INTO questions (test_id, position, prompt, options, correct_index) VALUES (?, ?, ?, ?, ?)',
  );

  const tests = [
    {
      title: 'JavaScript Fundamentals',
      description: 'A short quiz covering the basics of modern JavaScript.',
      passMark: 60,
      questions: [
        {
          prompt: 'Which keyword declares a block-scoped variable that can be reassigned?',
          options: ['var', 'let', 'const', 'static'],
          correct: 1,
        },
        {
          prompt: 'What does `Array.prototype.map` return?',
          options: ['The original array', 'A new array of transformed values', 'A single value', 'undefined'],
          correct: 1,
        },
        {
          prompt: 'Which of these is a strict equality comparison?',
          options: ['==', '===', '=', '=>'],
          correct: 1,
        },
        {
          prompt: 'What is the result of `typeof null`?',
          options: ['"null"', '"undefined"', '"object"', '"number"'],
          correct: 2,
        },
        {
          prompt: 'Which method converts a JSON string into an object?',
          options: ['JSON.stringify', 'JSON.parse', 'JSON.toObject', 'Object.fromJSON'],
          correct: 1,
        },
      ],
    },
    {
      title: 'HTTP & REST Basics',
      description: 'Check your knowledge of HTTP methods and REST conventions.',
      passMark: 50,
      questions: [
        {
          prompt: 'Which HTTP method is conventionally used to create a resource?',
          options: ['GET', 'POST', 'DELETE', 'HEAD'],
          correct: 1,
        },
        {
          prompt: 'What does the 404 status code mean?',
          options: ['Server error', 'Resource not found', 'Unauthorized', 'Redirect'],
          correct: 1,
        },
        {
          prompt: 'Which header declares the request body content type?',
          options: ['Accept', 'Content-Type', 'Authorization', 'Cache-Control'],
          correct: 1,
        },
      ],
    },
  ];

  for (const t of tests) {
    const { lastInsertRowid: testId } = insertTest.run(t.title, t.description, t.passMark);
    t.questions.forEach((q, i) => {
      insertQuestion.run(Number(testId), i + 1, q.prompt, JSON.stringify(q.options), q.correct);
    });
  }
}
