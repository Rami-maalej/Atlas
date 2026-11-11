import Database from 'better-sqlite3';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.TESTHUB_DATA_DIR ?? path.join(__dirname, '..', 'data');

const SCHEMA = `
CREATE TABLE IF NOT EXISTS tests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  pass_percent INTEGER NOT NULL DEFAULT 60,
  shuffle INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  prompt TEXT NOT NULL,
  points INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS choices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  text TEXT NOT NULL,
  is_correct INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  max_score REAL NOT NULL,
  percent REAL NOT NULL,
  passed INTEGER NOT NULL,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  choice_id INTEGER REFERENCES choices(id) ON DELETE SET NULL,
  is_correct INTEGER NOT NULL DEFAULT 0,
  points_awarded REAL NOT NULL DEFAULT 0
);
`;

/**
 * Opens (and migrates) a SQLite database at the given path.
 * Exported so tests can create isolated databases per suite.
 */
export function openDb(file) {
  const dir = path.dirname(file);
  fs.mkdirSync(dir, { recursive: true });
  const db = new Database(file);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');
  db.exec(SCHEMA);
  return db;
}

let db = null;

export function getDb() {
  if (!db) {
    db = openDb(process.env.TESTHUB_DB_FILE ?? path.join(DATA_DIR, 'testhub.db'));
    seedIfEmpty(db);
  }
  return db;
}

export function closeDb() {
  if (db) {
    db.close();
    db = null;
  }
}

function seedIfEmpty(database) {
  const { n } = database.prepare('SELECT COUNT(*) AS n FROM tests').get();
  if (n > 0) return;

  const insertTest = database.prepare(
    'INSERT INTO tests (title, description, pass_percent, shuffle) VALUES (?, ?, ?, ?)',
  );
  const insertQuestion = database.prepare(
    'INSERT INTO questions (test_id, position, prompt, points) VALUES (?, ?, ?, ?)',
  );
  const insertChoice = database.prepare(
    'INSERT INTO choices (question_id, position, text, is_correct) VALUES (?, ?, ?, ?)',
  );

  database.transaction(() => {
    const testId = insertTest.run(
      'Sample: JavaScript Basics',
      'A short demo test so you can try TestHub immediately.',
      60,
      0,
    ).lastInsertRowid;

    const questions = [
      {
        prompt: 'Which keyword declares a block-scoped variable?',
        points: 1,
        choices: [
          ['var', false],
          ['let', true],
          ['function', false],
          ['static', false],
        ],
      },
      {
        prompt: 'What does `Array.isArray([])` return?',
        points: 1,
        choices: [
          ['undefined', false],
          ['false', false],
          ['true', true],
          ['It throws', false],
        ],
      },
      {
        prompt: 'Which method converts JSON text into an object?',
        points: 2,
        choices: [
          ['JSON.stringify', false],
          ['JSON.parse', true],
          ['Object.fromJSON', false],
          ['JSON.decode', false],
        ],
      },
    ];

    questions.forEach((q, qi) => {
      const questionId = insertQuestion.run(testId, qi + 1, q.prompt, q.points).lastInsertRowid;
      q.choices.forEach(([text, correct], ci) => {
        insertChoice.run(questionId, ci + 1, text, correct ? 1 : 0);
      });
    });
  })();
}
