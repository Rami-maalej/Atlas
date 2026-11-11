import { api } from '../api.js';
import { h, render, toast, errorBanner, clear } from '../ui.js';

function blankTest() {
  return {
    title: '',
    description: '',
    passPercent: 60,
    shuffle: false,
    questions: [blankQuestion()],
  };
}

function blankQuestion() {
  return {
    prompt: '',
    points: 1,
    choices: [
      { text: '', isCorrect: true },
      { text: '', isCorrect: false },
    ],
  };
}

export async function editorView(params) {
  const root = document.querySelector('#app');
  const testId = params.id ? Number(params.id) : null;
  let model;
  let loadError = null;

  if (testId) {
    try {
      const { test } = await api.getTest(testId);
      model = {
        title: test.title,
        description: test.description,
        passPercent: test.passPercent,
        shuffle: test.shuffle,
        questions: test.questions.map((q) => ({
          id: q.id,
          prompt: q.prompt,
          points: q.points,
          choices: q.choices.map((c) => ({ id: c.id, text: c.text, isCorrect: c.isCorrect })),
        })),
      };
    } catch (error) {
      loadError = error;
    }
  } else {
    model = blankTest();
  }

  if (loadError) {
    render(
      root,
      errorBanner(loadError),
      h('a.btn', { href: '#/' }, '← Back to tests'),
    );
    return;
  }

  const bannerHost = h('div', {});
  const questionsHost = h('div.questions', {});

  const titleInput = h('input.input', {
    type: 'text',
    id: 'f-title',
    value: model.title,
    placeholder: 'e.g. Algebra Midterm',
    onInput: (e) => (model.title = e.target.value),
  });
  const descInput = h('textarea.input', {
    id: 'f-desc',
    rows: '2',
    placeholder: 'Optional description',
    onInput: (e) => (model.description = e.target.value),
  });
  descInput.value = model.description;

  const passInput = h('input.input.input-sm', {
    type: 'number',
    id: 'f-pass',
    min: '0',
    max: '100',
    value: String(model.passPercent),
    onInput: (e) => (model.passPercent = Number(e.target.value)),
  });
  const shuffleInput = h('input', {
    type: 'checkbox',
    id: 'f-shuffle',
    checked: model.shuffle,
    onChange: (e) => (model.shuffle = e.target.checked),
  });

  function renderQuestions() {
    clear(questionsHost);
    model.questions.forEach((question, qi) => {
      questionsHost.append(questionCard(question, qi));
    });
  }

  function questionCard(question, qi) {
    const promptInput = h('textarea.input', {
      rows: '2',
      placeholder: 'Write the question…',
      onInput: (e) => (question.prompt = e.target.value),
    });
    promptInput.value = question.prompt;

    const choicesHost = h('div.choices', {});
    const renderChoices = () => {
      clear(choicesHost);
      question.choices.forEach((choice, ci) => {
        const radio = h('input', {
          type: 'radio',
          name: `correct-q${qi}`,
          title: 'Mark as correct answer',
          checked: choice.isCorrect,
          onChange: () => {
            question.choices.forEach((c, i) => (c.isCorrect = i === ci));
            renderChoices();
          },
        });
        const textInput = h('input.input', {
          type: 'text',
          placeholder: `Choice ${ci + 1}`,
          value: choice.text,
          onInput: (e) => (choice.text = e.target.value),
        });
        const removeBtn = h(
          'button.icon-btn',
          {
            type: 'button',
            title: 'Remove choice',
            disabled: question.choices.length <= 2,
            onClick: () => {
              const wasCorrect = choice.isCorrect;
              question.choices.splice(ci, 1);
              if (wasCorrect) question.choices[0].isCorrect = true;
              renderChoices();
            },
          },
          '×',
        );
        choicesHost.append(h('div.choice-row', {}, radio, textInput, removeBtn));
      });
    };
    renderChoices();

    return h(
      'article.card.question',
      { 'data-q': String(qi) },
      h(
        'div.q-head',
        {},
        h('span.q-number', {}, `Q${qi + 1}`),
        h('input.input.input-sm', {
          type: 'number',
          min: '1',
          max: '100',
          title: 'Points',
          value: String(question.points),
          onInput: (e) => (question.points = Number(e.target.value)),
        }),
        h(
          'button.icon-btn',
          {
            type: 'button',
            title: 'Delete question',
            disabled: model.questions.length <= 1,
            onClick: () => {
              model.questions.splice(qi, 1);
              renderQuestions();
            },
          },
          '🗑',
        ),
      ),
      promptInput,
      choicesHost,
      h(
        'button.btn.btn-ghost',
        {
          type: 'button',
          onClick: () => {
            question.choices.push({ text: '', isCorrect: false });
            renderChoices();
          },
        },
        '+ Add choice',
      ),
    );
  }

  renderQuestions();

  async function save() {
    const payload = {
      title: model.title,
      description: model.description,
      passPercent: model.passPercent,
      shuffle: model.shuffle,
      questions: model.questions.map((q) => ({
        ...(q.id ? { id: q.id } : {}),
        prompt: q.prompt,
        points: q.points,
        choices: q.choices.map((c) => ({
          ...(c.id ? { id: c.id } : {}),
          text: c.text,
          isCorrect: c.isCorrect,
        })),
      })),
    };

    const saveBtn = document.querySelector('#save-btn');
    saveBtn.disabled = true;
    try {
      if (testId) {
        await api.updateTest(testId, payload);
        toast('Test updated', 'success');
      } else {
        await api.createTest(payload);
        toast('Test created', 'success');
      }
      location.hash = '#/';
    } catch (error) {
      render(bannerHost, errorBanner(error));
      bannerHost.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } finally {
      saveBtn.disabled = false;
    }
  }

  render(
    root,
    bannerHost,
    h(
      'div.page-head',
      {},
      h(
        'div',
        {},
        h('h1', {}, testId ? 'Edit test' : 'New test'),
        h('p.sub', {}, 'One correct answer per question. Points drive the score.'),
      ),
      h('a.btn', { href: '#/' }, 'Cancel'),
    ),
    h(
      'section.card.form-section',
      {},
      h('h3', {}, 'Details'),
      h('label.field', {}, 'Title', titleInput),
      h('label.field', {}, 'Description', descInput),
      h(
        'div.field-row',
        {},
        h('label.field', {}, 'Pass mark (%)', passInput),
        h(
          'label.field.field-check',
          {},
          shuffleInput,
          ' Shuffle questions when taking the test',
        ),
      ),
    ),
    h('div.page-head', {}, h('h3', {}, 'Questions')),
    questionsHost,
    h(
      'div.form-actions',
      {},
      h('button.btn.btn-ghost', { type: 'button', onClick: () => {
        model.questions.push(blankQuestion());
        renderQuestions();
      } }, '+ Add question'),
      h('button.btn.btn-primary', { type: 'button', id: 'save-btn', onClick: save }, 'Save test'),
    ),
  );
}
