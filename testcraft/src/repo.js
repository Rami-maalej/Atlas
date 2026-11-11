import { db } from './db.js';
import { ApiError } from './middleware/errors.js';

function rowToTest(row) {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    passMark: row.pass_mark,
    createdAt: row.created_at,
  };
}

function rowToQuestion(row) {
  return {
    id: row.id,
    position: row.position,
    prompt: row.prompt,
    options: JSON.parse(row.options),
    correctIndex: row.correct_index,
  };
}

export function listTests() {
  const rows = db
    .prepare(
      `SELECT t.*, COUNT(DISTINCT q.id) AS question_count, COUNT(DISTINCT a.id) AS attempt_count
       FROM tests t
       LEFT JOIN questions q ON q.test_id = t.id
       LEFT JOIN attempts a ON a.test_id = t.id
       GROUP BY t.id
       ORDER BY t.created_at DESC, t.id DESC`,
    )
    .all();
  return rows.map((r) => ({
    ...rowToTest(r),
    questionCount: r.question_count,
    attemptCount: r.attempt_count,
  }));
}

export function getTest(id, { withAnswers = true } = {}) {
  const row = db.prepare('SELECT * FROM tests WHERE id = ?').get(id);
  if (!row) throw new ApiError(404, `Test ${id} not found`);

  const questions = db
    .prepare('SELECT * FROM questions WHERE test_id = ? ORDER BY position, id')
    .all(id)
    .map(rowToQuestion);

  return {
    ...rowToTest(row),
    questions: questions.map((q) =>
      withAnswers ? q : { id: q.id, position: q.position, prompt: q.prompt, options: q.options },
    ),
  };
}

export function createTest(input) {
  const insertTest = db.prepare(
    'INSERT INTO tests (title, description, pass_mark) VALUES (?, ?, ?)',
  );
  const insertQuestion = db.prepare(
    'INSERT INTO questions (test_id, position, prompt, options, correct_index) VALUES (?, ?, ?, ?, ?)',
  );

  db.exec('BEGIN');
  try {
    const { lastInsertRowid } = insertTest.run(input.title, input.description, input.passMark);
    const testId = Number(lastInsertRowid);
    input.questions.forEach((q, i) => {
      insertQuestion.run(testId, i + 1, q.prompt, JSON.stringify(q.options), q.correctIndex);
    });
    db.exec('COMMIT');
    return getTest(testId);
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

export function updateTest(id, input) {
  getTest(id);

  const updateTestStmt = db.prepare(
    'UPDATE tests SET title = ?, description = ?, pass_mark = ? WHERE id = ?',
  );
  const deleteQuestions = db.prepare('DELETE FROM questions WHERE test_id = ?');
  const deleteAttempts = db.prepare('DELETE FROM attempts WHERE test_id = ?');
  const insertQuestion = db.prepare(
    'INSERT INTO questions (test_id, position, prompt, options, correct_index) VALUES (?, ?, ?, ?, ?)',
  );

  db.exec('BEGIN');
  try {
    updateTestStmt.run(input.title, input.description, input.passMark, id);
    deleteQuestions.run(id);
    deleteAttempts.run(id); // answers reference old questions; history is reset on edit
    input.questions.forEach((q, i) => {
      insertQuestion.run(id, i + 1, q.prompt, JSON.stringify(q.options), q.correctIndex);
    });
    db.exec('COMMIT');
    return getTest(id);
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

export function deleteTest(id) {
  getTest(id);
  const del = db.prepare('DELETE FROM tests WHERE id = ?');
  const result = del.run(id);
  if (result.changes === 0) throw new ApiError(404, `Test ${id} not found`);
  return { deleted: true, id };
}

export function saveAttempt({ testId, score, correctCount, total, passed, durationMs, answers }) {
  const test = getTest(testId);

  const insertAttempt = db.prepare(
    `INSERT INTO attempts (test_id, score, correct_count, total, passed, duration_ms)
     VALUES (?, ?, ?, ?, ?, ?)`,
  );
  const insertAnswer = db.prepare(
    `INSERT INTO attempt_answers (attempt_id, question_id, chosen_index, is_correct)
     VALUES (?, ?, ?, ?)`,
  );

  db.exec('BEGIN');
  try {
    const { lastInsertRowid } = insertAttempt.run(
      testId,
      score,
      correctCount,
      total,
      passed ? 1 : 0,
      durationMs,
    );
    const attemptId = Number(lastInsertRowid);
    answers.forEach((a, i) => {
      insertAnswer.run(attemptId, test.questions[i].id, a.chosenIndex, a.isCorrect ? 1 : 0);
    });
    db.exec('COMMIT');
    return getAttempt(attemptId);
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
}

export function getAttempt(id) {
  const row = db.prepare('SELECT * FROM attempts WHERE id = ?').get(id);
  if (!row) throw new ApiError(404, `Attempt ${id} not found`);

  const answers = db
    .prepare(
      `SELECT aa.question_id, aa.chosen_index, aa.is_correct, q.prompt, q.options, q.correct_index, q.position
       FROM attempt_answers aa
       JOIN questions q ON q.id = aa.question_id
       WHERE aa.attempt_id = ?
       ORDER BY q.position, q.id`,
    )
    .all(id);

  return {
    id: row.id,
    testId: row.test_id,
    score: row.score,
    correctCount: row.correct_count,
    total: row.total,
    passed: row.passed === 1,
    durationMs: row.duration_ms,
    createdAt: row.created_at,
    questions: answers.map((a) => ({
      questionId: a.question_id,
      prompt: a.prompt,
      options: JSON.parse(a.options),
      chosenIndex: a.chosen_index,
      correctIndex: a.correct_index,
      isCorrect: a.is_correct === 1,
    })),
  };
}

export function listAttempts(testId) {
  getTest(testId, { withAnswers: false });
  return db
    .prepare(
      `SELECT id, score, correct_count, total, passed, duration_ms, created_at
       FROM attempts WHERE test_id = ? ORDER BY created_at DESC, id DESC`,
    )
    .all(testId)
    .map((r) => ({
      id: r.id,
      testId,
      score: r.score,
      correctCount: r.correct_count,
      total: r.total,
      passed: r.passed === 1,
      durationMs: r.duration_ms,
      createdAt: r.created_at,
    }));
}

/**
 * Validate submitted answers against the stored test and return normalized answer rows
 * aligned with the test's question order.
 */
export function buildAnswers(test, submitted) {
  const byQuestionId = new Map(submitted.map((a) => [a.questionId, a.chosenIndex]));
  const seen = new Set();

  return test.questions.map((q) => {
    if (seen.has(q.id)) throw new ApiError(400, 'Duplicate question id in answers');
    seen.add(q.id);

    const raw = byQuestionId.get(q.id);
    let chosen = null;
    if (raw !== undefined && raw !== null && raw >= 0) {
      if (raw >= q.options.length) {
        throw new ApiError(400, `Answer index out of range for question ${q.id}`);
      }
      chosen = raw;
    }
    return { chosen, correct: q.correctIndex };
  });
}
