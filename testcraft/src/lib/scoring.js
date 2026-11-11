/**
 * Pure scoring logic: no I/O, easy to unit test.
 * @param {Array<{chosen: number|null, correct: number}>} answers
 * @param {number} passMark percentage (0-100) required to pass
 */
export function scoreAttempt(answers, passMark) {
  const total = answers.length;
  if (total === 0) {
    return { score: 0, correctCount: 0, total: 0, passed: false, details: [] };
  }

  let correctCount = 0;
  const details = answers.map((a) => {
    const isCorrect = a.chosen !== null && a.chosen === a.correct;
    if (isCorrect) correctCount += 1;
    return { chosen: a.chosen, correct: a.correct, isCorrect };
  });

  const score = Math.round((correctCount / total) * 1000) / 10;
  const passed = score >= passMark;

  return { score, correctCount, total, passed, details };
}
