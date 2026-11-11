/** Pure scoring logic — kept separate so it is trivially unit-testable. */

/**
 * @param {{points: number, isCorrect: boolean}[]} graded Answers for one attempt
 * @returns {{score: number, maxScore: number, percent: number}}
 */
export function scoreAttempt(graded) {
  const maxScore = graded.reduce((sum, g) => sum + g.points, 0);
  const score = graded.reduce((sum, g) => sum + (g.isCorrect ? g.points : 0), 0);
  const percent = maxScore === 0 ? 100 : Math.round((score / maxScore) * 10000) / 100;
  return { score, maxScore, percent };
}

export function hasPassed(percent, passPercent) {
  return percent >= passPercent;
}
