import { scoreAttempt, hasPassed } from './lib/scoring.js';

/* ---------------------------------- tests --------------------------------- */

export function listTests(db) {
  return db
    .prepare(
      `SELECT t.id, t.title, t.description, t.pass_percent AS passPercent,
              t.shuffle, t.created_at AS createdAt,
              (SELECT COUNT(*) FROM questions q WHERE q.test_id = t.id) AS questionCount,
              (SELECT COUNT(*) FROM attempts a WHERE a.test_id = t.id) AS attemptCount,
              (SELECT ROUND(AVG(a.percent), 2) FROM attempts a WHERE a.test_id = t.id) AS avgPercent
       FROM tests t
       ORDER BY t.created_at DESC, t.id DESC`,
    )
    .all();
}

/** Prepared statements cached per database handle (tests may open several). */
const stmtCache = new WeakMap();

function statements(db) {
  let s = stmtCache.get(db);
  if (!s) {
    s = {
      questions: db.prepare(
        'SELECT id, position, prompt, points FROM questions WHERE test_id = ? ORDER BY position',
      ),
      choices: db.prepare(
        'SELECT id, text, is_correct FROM choices WHERE question_id = ? ORDER BY position',
      ),
    };
    stmtCache.set(db, s);
  }
  return s;
}

function rowToTest(db, row, { includeAnswers }) {
  const s = statements(db);
  const questions = s.questions.all(row.id).map((q) => ({
    id: q.id,
    position: q.position,
    prompt: q.prompt,
    points: q.points,
    choices: s.choices.all(q.id).map((c) => ({
      id: c.id,
      text: c.text,
      ...(includeAnswers ? { isCorrect: c.is_correct === 1 } : {}),
    })),
  }));

  return {
    id: row.id,
    title: row.title,
    description: row.description,
    passPercent: row.pass_percent,
    shuffle: row.shuffle === 1,
    createdAt: row.created_at,
    questions,
  };
}

export function getTest(db, id, { includeAnswers = true } = {}) {
  const row = db.prepare('SELECT * FROM tests WHERE id = ?').get(id);
  if (!row) return null;
  return rowToTest(db, row, { includeAnswers });
}

export function deleteTest(db, id) {
  const info = db.prepare('DELETE FROM tests WHERE id = ?').run(id);
  return info.changes > 0;
}

export function createTest(db, input) {
  const tx = db.transaction(() => {
    const testId = db
      .prepare('INSERT INTO tests (title, description, pass_percent, shuffle) VALUES (?, ?, ?, ?)')
      .run(input.title, input.description, input.passPercent, input.shuffle ? 1 : 0).lastInsertRowid;
    insertQuestions(db, testId, input.questions);
    return testId;
  });
  return tx();
}

export function updateTest(db, id, input) {
  const tx = db.transaction(() => {
    const info = db
      .prepare('UPDATE tests SET title = ?, description = ?, pass_percent = ?, shuffle = ? WHERE id = ?')
      .run(input.title, input.description, input.passPercent, input.shuffle ? 1 : 0, id);
    if (info.changes === 0) return false;

    const existingQuestionIds = new Set(
      db.prepare('SELECT id FROM questions WHERE test_id = ?').all(id).map((r) => r.id),
    );
    const kept = new Set();

    input.questions.forEach((q, index) => {
      let questionId;
      if (q.id && existingQuestionIds.has(q.id)) {
        questionId = q.id;
        db.prepare('UPDATE questions SET position = ?, prompt = ?, points = ? WHERE id = ?').run(
          index + 1,
          q.prompt,
          q.points,
          questionId,
        );
        db.prepare('DELETE FROM choices WHERE question_id = ?').run(questionId);
      } else {
        questionId = db
          .prepare('INSERT INTO questions (test_id, position, prompt, points) VALUES (?, ?, ?, ?)')
          .run(id, index + 1, q.prompt, q.points).lastInsertRowid;
      }
      kept.add(questionId);
      insertChoices(db, questionId, q.choices);
    });

    for (const questionId of existingQuestionIds) {
      if (!kept.has(questionId)) {
        db.prepare('DELETE FROM questions WHERE id = ?').run(questionId);
      }
    }
    return true;
  });
  return tx();
}

function insertQuestions(db, testId, questions) {
  questions.forEach((q, index) => {
    const questionId = db
      .prepare('INSERT INTO questions (test_id, position, prompt, points) VALUES (?, ?, ?, ?)')
      .run(testId, index + 1, q.prompt, q.points).lastInsertRowid;
    insertChoices(db, questionId, q.choices);
  });
}

function insertChoices(db, questionId, choices) {
  choices.forEach((c, index) => {
    db.prepare('INSERT INTO choices (question_id, position, text, is_correct) VALUES (?, ?, ?, ?)').run(
      questionId,
      index + 1,
      c.text,
      c.isCorrect ? 1 : 0,
    );
  });
}

/* -------------------------------- attempts -------------------------------- */

export function createAttempt(db, testId, input) {
  const test = getTest(db, testId, { includeAnswers: true });
  if (!test) return null;

  const answerByQuestion = new Map(input.answers.map((a) => [a.questionId, a.choiceId]));
  const questionById = new Map(test.questions.map((q) => [q.id, q]));
  const graded = [];

  for (const question of test.questions) {
    const givenChoiceId = answerByQuestion.get(question.id);
    if (givenChoiceId === undefined) continue;

    if (givenChoiceId !== null) {
      const belongs = question.choices.some((c) => c.id === givenChoiceId);
      if (!belongs) {
        const err = new Error(
          `Choice ${givenChoiceId} does not belong to question ${question.id}`,
        );
        err.status = 400;
        err.code = 'INVALID_CHOICE';
        throw err;
      }
    }
    const correctChoice = question.choices.find((c) => c.isCorrect);
    graded.push({
      question,
      givenChoiceId,
      points: question.points,
      isCorrect: givenChoiceId !== null && givenChoiceId === correctChoice?.id,
    });
  }

  if (graded.length === 0) {
    const err = new Error('No answers matched the questions of this test');
    err.status = 400;
    err.code = 'NO_ANSWERS';
    throw err;
  }

  const { score, maxScore, percent } = scoreAttempt(
    graded.map((g) => ({ points: g.points, isCorrect: g.isCorrect })),
  );
  const passed = hasPassed(percent, test.passPercent);

  const tx = db.transaction(() => {
    const attemptId = db
      .prepare(
        `INSERT INTO attempts (test_id, score, max_score, percent, passed)
         VALUES (?, ?, ?, ?, ?)`,
      )
      .run(testId, score, maxScore, percent, passed ? 1 : 0).lastInsertRowid;

    const insertAnswer = db.prepare(
      `INSERT INTO answers (attempt_id, question_id, choice_id, is_correct, points_awarded)
       VALUES (?, ?, ?, ?, ?)`,
    );
    for (const g of graded) {
      insertAnswer.run(
        attemptId,
        g.question.id,
        g.givenChoiceId,
        g.isCorrect ? 1 : 0,
        g.isCorrect ? g.points : 0,
      );
    }
    return attemptId;
  });

  const attemptId = tx();
  return getAttempt(db, attemptId);
}

export function listAttempts(db) {
  return db
    .prepare(
      `SELECT a.id, a.test_id AS testId, t.title AS testTitle, a.score, a.max_score AS maxScore,
              a.percent, a.passed, a.submitted_at AS submittedAt
       FROM attempts a
       JOIN tests t ON t.id = a.test_id
       ORDER BY a.submitted_at DESC, a.id DESC`,
    )
    .all()
    .map((row) => ({ ...row, passed: row.passed === 1 }));
}

export function getAttempt(db, id) {
  const row = db
    .prepare(
      `SELECT a.*, t.title AS test_title, t.pass_percent AS pass_percent
       FROM attempts a
       JOIN tests t ON t.id = a.test_id
       WHERE a.id = ?`,
    )
    .get(id);
  if (!row) return null;

  const answers = db
    .prepare(
      `SELECT an.question_id AS questionId, an.choice_id AS choiceId, an.is_correct AS isCorrect,
              an.points_awarded AS pointsAwarded,
              q.prompt, q.points,
              c.text AS chosenText,
              (SELECT text FROM choices WHERE question_id = q.id AND is_correct = 1) AS correctText
       FROM answers an
       JOIN questions q ON q.id = an.question_id
       LEFT JOIN choices c ON c.id = an.choice_id
       WHERE an.attempt_id = ?
       ORDER BY q.position`,
    )
    .all(id);

  return {
    id: row.id,
    testId: row.test_id,
    testTitle: row.test_title,
    score: row.score,
    maxScore: row.max_score,
    percent: row.percent,
    passed: row.passed === 1,
    passPercent: row.pass_percent,
    submittedAt: row.submitted_at,
    answers: answers.map((a) => ({
      questionId: a.questionId,
      prompt: a.prompt,
      points: a.points,
      choiceId: a.choiceId,
      chosenText: a.chosenText ?? null,
      correctText: a.correctText,
      isCorrect: a.isCorrect === 1,
      pointsAwarded: a.pointsAwarded,
    })),
  };
}

export function testStats(db, testId) {
  return db
    .prepare(
      `SELECT COUNT(*) AS attempts,
              COALESCE(ROUND(AVG(percent), 2), 0) AS avgPercent,
              COALESCE(MAX(percent), 0) AS bestPercent
       FROM attempts WHERE test_id = ?`,
    )
    .get(testId);
}
