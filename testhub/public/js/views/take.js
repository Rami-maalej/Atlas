import { api } from '../api.js';
import { h, render, toast, errorBanner, percentBadge, formatDate } from '../ui.js';

export async function takeView(params) {
  const root = document.querySelector('#app');
  const testId = Number(params.id);
  let test;

  try {
    ({ test } = await api.getTakeableTest(testId));
  } catch (error) {
    render(root, errorBanner(error), h('a.btn', { href: '#/' }, '← Back to tests'));
    return;
  }

  if (test.questions.length === 0) {
    render(root, errorBanner({ message: 'This test has no questions yet.' }));
    return;
  }

  const questions = test.shuffle ? shuffle([...test.questions]) : test.questions;
  const selections = new Map(); // questionId -> choiceId | null
  const bannerHost = h('div', {});

  const form = h(
    'form.take-form',
    {
      onSubmit: async (e) => {
        e.preventDefault();
        const missing = test.questions.filter((q) => !selections.has(q.id));
        if (missing.length > 0) {
          toast(`Please answer question${missing.length > 1 ? 's' : ''} ${missing
            .map((q) => test.questions.indexOf(q) + 1)
            .join(', ')}`, 'error');
          return;
        }
        const submitBtn = form.querySelector('button[type=submit]');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Scoring…';
        try {
          const { attempt } = await api.submitAttempt(
            testId,
            test.questions.map((q) => ({
              questionId: q.id,
              choiceId: selections.get(q.id) ?? null,
            })),
          );
          location.hash = `#/attempts/${attempt.id}`;
        } catch (error) {
          render(bannerHost, errorBanner(error));
          submitBtn.disabled = false;
          submitBtn.textContent = 'Submit answers';
        }
      },
    },
    questions.map((q, index) =>
      h(
        'fieldset.card.question',
        { disabled: false },
        h(
          'legend.q-legend',
          {},
          h('span.q-number', {}, `Q${index + 1}`),
          h('span.q-points', {}, `${q.points} pt${q.points === 1 ? '' : 's'}`),
        ),
        h('p.prompt', {}, q.prompt),
        ...q.choices.map((choice) =>
          h(
            'label.choice',
            {},
            h('input', {
              type: 'radio',
              name: `q-${q.id}`,
              value: String(choice.id),
              onChange: () => selections.set(q.id, choice.id),
            }),
            h('span', {}, choice.text),
          ),
        ),
      ),
    ),
    h(
      'div.form-actions',
      {},
      h('a.btn', { href: '#/' }, 'Cancel'),
      h('button.btn.btn-primary', { type: 'submit' }, 'Submit answers'),
    ),
  );

  render(
    root,
    h(
      'div.page-head',
      {},
      h(
        'div',
        {},
        h('h1', {}, test.title),
        h('p.sub', {}, test.description || `${test.questions.length} questions · pass mark ${test.passPercent}%`),
      ),
      h('span.badge', {}, `Pass ≥ ${test.passPercent}%`),
    ),
    bannerHost,
    form,
  );
}

export async function historyView() {
  const root = document.querySelector('#app');
  try {
    const { attempts } = await api.listAttempts();
    const rows = attempts.map((a) =>
      h(
        'tr',
        {},
        h('td', {}, h('a', { href: `#/attempts/${a.id}` }, a.testTitle)),
        h('td', {}, `${a.score}/${a.maxScore}`),
        h('td', {}, percentBadge(a.percent)),
        h('td', {}, a.passed ? h('span.badge.ok', {}, 'Passed') : h('span.badge.bad', {}, 'Failed')),
        h('td', {}, formatDate(a.submittedAt)),
      ),
    );

    render(
      root,
      h(
        'div.page-head',
        {},
        h('div', {}, h('h1', {}, 'Results'), h('p.sub', {}, `${attempts.length} attempt${attempts.length === 1 ? '' : 's'}`)),
      ),
      attempts.length === 0
        ? h('div.empty', {}, h('p', {}, 'No attempts yet. Take a test to see results here.'))
        : h(
            'table.table',
            {},
            h(
              'thead',
              {},
              h('tr', {}, h('th', {}, 'Test'), h('th', {}, 'Score'), h('th', {}, 'Percent'), h('th', {}, 'Status'), h('th', {}, 'Submitted')),
            ),
            h('tbody', {}, rows),
          ),
    );
  } catch (error) {
    render(root, errorBanner(error));
  }
}

export async function resultView(params) {
  const root = document.querySelector('#app');
  let attempt;
  try {
    ({ attempt } = await api.getAttempt(Number(params.id)));
  } catch (error) {
    render(root, errorBanner(error), h('a.btn', { href: '#/' }, '← Back to tests'));
    return;
  }

  const review = attempt.answers.map((a, index) =>
    h(
      `article.card.answer.${a.isCorrect ? 'correct' : 'wrong'}`,
      {},
      h(
        'div.a-head',
        {},
        h(`span.dot.${a.isCorrect ? 'ok' : 'bad'}`, {}, a.isCorrect ? '✓' : '✗'),
        h('span.q-number', {}, `Q${index + 1}`),
        h('span.q-points', {}, `${a.pointsAwarded}/${a.points} pts`),
      ),
      h('p.prompt', {}, a.prompt),
      h('p.line', {}, 'Your answer: ', h('strong', {}, a.chosenText ?? '(skipped)')),
      a.isCorrect
        ? null
        : h('p.line', {}, 'Correct answer: ', h('strong', {}, a.correctText)),
    ),
  );

  render(
    root,
    h(
      'section.card.result-hero',
      {},
      h('p.sub', {}, attempt.testTitle),
      h('div.score', {}, formatScore(attempt.percent)),
      h(
        'div.score-meta',
        {},
        h(`span.badge.${attempt.passed ? 'ok' : 'bad'}`, {}, attempt.passed ? 'PASSED' : 'FAILED'),
        h('span', {}, `${attempt.score} / ${attempt.maxScore} points`),
        h('span', {}, `Pass mark: ${attempt.passPercent}%`),
        h('span', {}, formatDate(attempt.submittedAt)),
      ),
      h(
        'div.card-actions',
        {},
        h('button.btn.btn-primary', { type: 'button', onClick: () => location.hash = `#/tests/${attempt.testId}/take` }, 'Retake test'),
        h('a.btn', { href: '#/history' }, 'All results'),
        h('a.btn', { href: '#/' }, 'Home'),
      ),
    ),
    h('h3.page-sub', {}, 'Question review'),
    h('div.review', {}, review),
  );
}

function formatScore(percent) {
  const n = Number(percent);
  return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
}

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
