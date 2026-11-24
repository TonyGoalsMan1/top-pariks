'use strict';

const $ = (id) => document.getElementById(id);
const field = (form, name) => $(form).elements.namedItem(name);
const terminal = new Set(['done', 'failed', 'blocked', 'cancelled']);
const statusLabel = {
  queued: 'В очереди', running: 'Выполняется', done: 'Завершена', failed: 'Ошибка',
  blocked: 'Заблокирована', cancelled: 'Отменена',
};
const operations = {
  code: 'Разработка', report: 'Отчёт', build: 'Сборка', start: 'Запуск стенда',
  health: 'Проверка стенда', backup: 'Создать копию', restore: 'Восстановить снимок', deploy: 'Публикация на тест',
};
const phases = { execute: 'Исполнение', publish: 'Открытие PR', ci: 'Проверки CI', merge: 'Ожидание слияния' };
const eventLabel = {
  ...statusLabel, started: 'Этап начат', held: 'Приостановлена', released: 'Возвращена в очередь',
  approved: 'Действие подтверждено', interrupted: 'Прервана', automatic_pause: 'Аварийная пауза',
  cancel_requested: 'Запрошена отмена', retried_from: 'Создан повтор', budget_reserved: 'Бюджет зарезервирован',
  ai_usage: 'Получена статистика токенов',
};

let account;
let project;
let selected;
let selectedVersion = 0;
let generation = 0;
let snapshot;
let older = [];
let nextPage;
let polling = false;
let mutations = 0;
const renderKeys = new WeakMap();

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function render(target, data, build) {
  const key = JSON.stringify(data);
  if (renderKeys.get(target) !== key) {
    target.replaceChildren(...build());
    renderKeys.set(target, key);
  }
}

function options(target, rows) {
  const old = target.value;
  render(target, rows, () => rows.map(([id, label]) => new Option(label, id)));
  if (rows.some(([id]) => id === old)) target.value = old;
}

function feedback(text = '') {
  $('feedback').textContent = text;
  $('feedback').hidden = !text;
}

function description(target, rows) {
  render(target, rows, () => rows.flatMap(([label, content]) =>
    [element('dt', label), element('dd', content)]));
}

function date(value) {
  return new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('ru-RU');
}

function money(amount) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6,
  }).format(amount / 1000000);
}

async function api(path, data) {
  const response = await fetch('/api/v1/' + path, {
    cache: 'no-store',
    ...(data === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
  });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== 'session') resetSession();
    throw new Error(body.error || 'Ошибка запроса');
  }
  return body;
}

function resetSession() {
  account = undefined;
  setProject(undefined);
  options($('projects'), []);
  options(field('register', 'project'), []);
  $('identity').hidden = true;
  $('workspace').hidden = true;
  $('login-screen').hidden = false;
}

function projectPath(action) {
  return 'projects/' + project.id + (action ? '/' + action : '');
}

function label(task) {
  return task.approval ? 'Ждёт разрешения' : task.cancelling ? 'Отмена запрошена'
    : task.held && task.status === 'queued' ? 'Остановлена' : statusLabel[task.status];
}

function control(text, handler) {
  const button = element('button', text);
  button.type = 'button';
  button.addEventListener('click', () => run(button, handler));
  return button;
}

function setProject(value) {
  generation += 1;
  project = value;
  selected = undefined;
  snapshot = undefined;
  older = [];
  nextPage = undefined;
  $('project-view').hidden = true;
  $('task-detail').hidden = true;
  $('task-detail').replaceChildren();
  renderKeys.delete($('task-detail'));
  $('audit').replaceChildren();
  renderKeys.delete($('audit'));
  $('audit-panel').open = false;
  $('business').reset();
  $('operations').reset();
  $('budget-form').reset();
  for (const id of ['tasks', 'notifications', 'backups', 'site-status', 'budget']) {
    $(id).replaceChildren();
    renderKeys.delete($(id));
  }
  if (value) $('projects').value = value.id;
}

async function loadProjects() {
  const data = await api('projects');
  account = data;
  $('username').textContent = data.user;
  $('identity').hidden = false;
  $('workspace').hidden = false;
  $('login-screen').hidden = true;
  $('no-project').hidden = data.projects.length > 0;
  $('register').hidden = data.available.length === 0;
  options($('projects'), data.projects.map(({ id }) => [id, id]));
  options(field('register', 'project'), data.available.map((id) => [id, id]));
  if (!project && data.projects.length > 0) setProject(data.projects[0]);
  await refresh();
}

async function refresh() {
  if (!project) return;
  const version = generation;
  const data = await api(projectPath());
  if (generation !== version) return;
  snapshot = data;
  if (!older.length) nextPage = data.next;
  renderDashboard();
  if (selected) await loadTask(selected, false);
}

function renderTasks() {
  const rows = [...snapshot.tasks, ...older.filter((row) => !snapshot.tasks.some((task) => task.id === row.id))];
  render($('tasks'), [rows.map((task) => [task.id, task.spec, label(task), task.status]), selected], () => {
    if (!rows.length) return [element('p', 'В очереди пока нет задач.', 'muted')];
    return rows.map((task) => {
      const button = control(task.spec.objective, () => loadTask(task.id, true));
      button.textContent = '';
      button.className = 'task-row';
      button.setAttribute('aria-current', String(task.id === selected));
      const name = element('span');
      name.append(element('strong', task.spec.objective), document.createElement('br'),
        element('span', operations[task.spec.operation] + (task.spec.role ? ' · ' + task.spec.role : '') +
          ' · ' + task.id.slice(0, 8), 'muted'));
      const badge = element('span', label(task), 'badge');
      badge.dataset.status = task.status;
      button.append(name, badge);
      return button;
    });
  });
  $('older-tasks').hidden = !nextPage;
  options(field('business', 'after'), [['', 'Без зависимости'], ...rows.map((task) =>
    [task.id, task.spec.objective.slice(0, 50) + ' · ' + task.id.slice(0, 8)])]);
}

function renderDashboard() {
  const data = snapshot;
  const editable = project.role !== 'viewer';
  $('project-title').textContent = data.project;
  $('executor').textContent = data.executor === 'mock' ? 'Демонстрация · Mock' : 'OpenAI Responses';
  $('dispatcher').textContent = data.dispatcher_paused ? 'На общей паузе' :
    data.dispatcher_online ? 'В сети' : 'Не в сети';
  $('queue-state').textContent = data.paused ? 'Приостановлена' : 'Принимает задачи';
  $('toggle-pause').textContent = data.paused ? 'Возобновить очередь' : 'Остановить очередь';
  $('toggle-pause').hidden = !editable;
  $('cost').textContent = money(data.budget.estimated_microdollars) + ' · оценка';
  const budget = data.budget;
  description($('budget'), [
    ['Модель', budget.model || 'Mock'], ['Зарезервировано', money(budget.reserved_microdollars)],
    ['Бюджет проекта', money(budget.total_microdollars || 0)],
    ['Действующий лимит', money(budget.limit_microdollars)],
    ['Лимиты ввода / вывода', (budget.max_input_tokens || 0) + ' / ' + (budget.max_output_tokens || 0)],
    ['Учтённые токены ввода / вывода', budget.input_tokens + ' / ' + budget.output_tokens],
  ]);
  $('budget-form').hidden = !account.owner || data.executor !== 'responses';
  field('budget-form', 'limit').max = budget.total_microdollars / 1000000;
  field('budget-form', 'limit').placeholder = String(budget.limit_microdollars / 1000000);
  $('new-task').hidden = !editable || data.business_roles.length === 0;
  options(field('business', 'role'), data.business_roles.map((role) => [role, role]));
  $('task-count').textContent = String(data.task_count);
  renderTasks();

  const site = data.site;
  description($('site-status'), site ? [
    ['Профиль', site.domain],
    ['Подготовка', site.provisioned ? 'Подготовлен ранее' : 'Ещё не подготовлен'],
    ['Журнал Factory', site.recovery_required ? 'Требуется восстановление' : 'Открытых операций нет'],
    ['Последняя проверка', site.health ? statusLabel[site.health.status] : 'Нет результатов'],
  ] : [['Профиль', 'Стенд не подключён']]);
  $('operations').hidden = !editable || data.operations.length === 0;
  const backups = site?.backups || [];
  options(field('operations', 'operation'), data.operations
    .filter((operation) => operation !== 'restore' || backups.length)
    .map((operation) => [operation, operations[operation]]));
  options(field('operations', 'backup'), backups.map(({ id }) => [id, id]));
  operationFields();
  render($('backups'), [backups, editable, data.operations], () => backups.length ?
    backups.map((backup) => {
      const item = element('li', backup.id);
      item.append(element('time', date(backup.created_at)));
      if (editable && data.operations.includes('restore')) {
        item.append(control('Выбрать для восстановления', () => {
          field('operations', 'operation').value = 'restore';
          field('operations', 'backup').value = backup.id;
          operationFields();
          field('operations', 'backup').focus();
        }));
      }
      return item;
    }) : [element('li', 'Копий пока нет.', 'muted')]);
  render($('notifications'), data.notifications, () => data.notifications.length ?
    data.notifications.map((notice) => {
      const item = element('li');
      item.append(control(notice.message + ' · ' + notice.job.slice(0, 8), async () => {
        await loadTask(notice.job, true);
        $('task-detail').scrollIntoView({ block: 'start' });
      }), element('time', date(notice.time)));
      return item;
    }) : [element('li', 'Новых событий пока нет.', 'muted')]);
  $('audit-panel').hidden = !account.owner;
  $('project-view').hidden = false;
}

function operationFields() {
  const operation = field('operations', 'operation').value;
  const usesRef = ['build', 'start', 'deploy'].includes(operation);
  $('ref-field').hidden = !usesRef;
  field('operations', 'ref').required = usesRef;
  field('operations', 'ref').disabled = !usesRef;
  $('backup-field').hidden = operation !== 'restore';
  field('operations', 'backup').required = operation === 'restore';
}

async function loadTask(id, focus) {
  if (focus) {
    selected = id;
    selectedVersion += 1;
  }
  const version = generation;
  const selection = selectedVersion;
  const task = await api(projectPath('tasks/' + id));
  if (version !== generation || selected !== id || selection !== selectedVersion) return;
  render($('task-detail'), task, () => taskDetails(task));
  $('task-detail').hidden = false;
  if (focus) {
    renderTasks();
    $('task-detail').focus();
  }
}

function taskDetails(task) {
  const heading = element('h3', task.spec.objective);
  const meta = element('dl');
  description(meta, [
    ['ID', task.id], ['Операция', operations[task.spec.operation] || task.spec.operation],
    ['Статус', label(task)], ['Этап', phases[task.phase] || task.phase],
    ['Попытка', String(task.attempt)], ['Поставлена', date(task.created)],
    ...(task.spec.ref ? [['Git SHA', task.spec.ref]] : []),
    ...(task.spec.backup ? [['Снимок', task.spec.backup]] : []),
  ]);
  const nodes = [heading, meta];
  if (task.dependencies.length) {
    const deps = element('div', undefined, 'actions');
    deps.append(element('p', 'Зависимости'));
    task.dependencies.forEach((dep) => deps.append(control(dep.slice(0, 8), () => loadTask(dep, true))));
    nodes.push(deps);
  }

  const result = task.result;
  if (result.pr_url) {
    const link = element('a', 'Открыть PR #' + result.pr);
    link.href = result.pr_url;
    nodes.push(link);
  }
  const resultRows = [
    ['Результат', result.summary], ['Ревью', result.review], ['Ошибка', result.failure],
    ['Commit', result.head || result.commit], ['Ветка', result.branch], ['Снимок', result.backup],
    ['Состояние PR', result.merged ? 'MERGED' : result.pr_state],
    ...(result.verified ? [['Проверка Factory', 'Успешна']] : []),
    ...Object.entries(result.checks || {}).map(([name, state]) => ['CI · ' + name, state || 'Ожидается']),
  ].filter(([, value]) => value);
  if (resultRows.length) {
    const output = element('dl');
    description(output, resultRows);
    nodes.push(output);
  }

  if (project.role !== 'viewer' && !task.cancelling) {
    const actions = element('div', undefined, 'actions');
    if (terminal.has(task.status)) {
      if (!task.spec.critical || (task.status === 'cancelled' && task.attempt === 0)) {
        actions.append(control('Повторить задачу', () => changeTask(task.id, 'retry')));
      }
    } else {
      actions.append(control(task.held ? 'Возобновить задачу' : 'Остановить задачу',
        () => changeTask(task.id, task.held ? 'release' : 'hold')));
      actions.append(control('Отменить задачу', () => changeTask(task.id, 'cancel')));
    }
    if (actions.childElementCount) nodes.push(actions);
    if (task.approval && account.owner) {
      const form = element('form');
      const consent = element('label', 'Подтверждаю: ' + operations[task.spec.operation] + ' · ' + project.id);
      const checkbox = element('input');
      checkbox.type = 'checkbox';
      checkbox.required = true;
      consent.prepend(checkbox);
      const button = element('button', 'Разрешить действие', 'primary');
      form.append(element('p', 'Версия ' + task.approval.slice(0, 12), 'muted'), consent, button);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        run(button, () => changeTask(task.id, 'approve', { version: task.approval, operation: task.spec.operation }));
      });
      nodes.push(form);
    }
  }
  const log = element('details');
  log.append(element('summary', 'Журнал исполнения · ' + task.events.length));
  const timeline = element('ol', undefined, 'records');
  task.events.forEach((event) => {
    const notes = [eventLabel[event.event] || event.event, event.detail.reason || event.detail.failure ||
      event.detail.summary || event.detail.role || ''].filter(Boolean);
    const item = element('li', notes.join(' · '));
    item.append(element('time', date(event.time)));
    timeline.append(item);
  });
  log.append(timeline);
  nodes.push(log);
  return nodes;
}

async function changeTask(id, action, data = {}) {
  const version = generation;
  const result = await api(projectPath('tasks/' + id + '/' + action), data);
  if (version !== generation) return;
  if (action === 'retry') selected = result.task;
  await refresh();
}

async function run(button, action) {
  if (button.disabled) return;
  button.disabled = true;
  mutations += 1;
  feedback();
  try {
    await action();
  } catch (error) {
    feedback(error.message);
  } finally {
    mutations -= 1;
    button.disabled = false;
  }
}

function formSubmit(id, action) {
  const form = $(id);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    run(form.querySelector('button'), () => action(values));
  });
}

formSubmit('login', async (values) => {
  try {
    await api('session', values);
    await loadProjects();
  } finally {
    field('login', 'password').value = '';
  }
});
formSubmit('register', async ({ project: id }) => {
  await api('projects/' + id + '/register', {});
  await loadProjects();
  setProject(account.projects.find((item) => item.id === id));
  await refresh();
});
formSubmit('business', async ({ objective, role, priority, after }) => {
  const version = generation;
  const data = await api(projectPath('business'), {
    objective, role, priority: Number(priority), after: after ? [after] : [],
  });
  if (version !== generation) return;
  $('business').reset();
  selected = data.tasks.at(-1);
  await refresh();
});
formSubmit('operations', async ({ operation, ref, backup }) => {
  const version = generation;
  const data = await api(projectPath('operations'), {
    objective: operations[operation], operation, ref: ref || null, backup: operation === 'restore' ? backup : null,
  });
  if (version !== generation) return;
  selected = data.tasks[0];
  await refresh();
});
formSubmit('budget-form', async ({ limit }) => {
  const version = generation;
  await api(projectPath('budget'), { limit_microdollars: Math.round(Number(limit) * 1000000) });
  if (version !== generation) return;
  $('budget-form').reset();
  await refresh();
});
field('operations', 'operation').addEventListener('change', operationFields);
$('projects').addEventListener('change', () => {
  feedback();
  setProject(account.projects.find(({ id }) => id === $('projects').value));
  refresh().catch((error) => feedback(error.message));
});
$('toggle-pause').addEventListener('click', () => run($('toggle-pause'), async () => {
  await api(projectPath(snapshot.paused ? 'resume' : 'pause'), {});
  await refresh();
}));
$('older-tasks').addEventListener('click', () => run($('older-tasks'), async () => {
  const version = generation;
  const data = await api(projectPath('tasks/before/' + nextPage));
  if (version !== generation) return;
  older.push(...data.tasks);
  nextPage = data.next;
  renderTasks();
}));
$('load-audit').addEventListener('click', () => run($('load-audit'), async () => {
  const version = generation;
  const data = await api(projectPath('audit'));
  if (version !== generation) return;
  render($('audit'), data.records, () => data.records.map((row) => {
    const item = element('li', [row.actor, row.action, row.target?.slice(0, 8)].filter(Boolean).join(' · '));
    item.append(element('time', date(row.at)));
    return item;
  }));
}));
$('logout').addEventListener('click', () => run($('logout'), async () => {
  await api('logout', {});
  resetSession();
}));

loadProjects().catch((error) => {
  if (account === undefined) resetSession();
  if (error.message !== 'Войдите в панель') feedback(error.message);
});
window.setInterval(async () => {
  if (!project || document.hidden || polling || mutations) return;
  polling = true;
  try {
    await refresh();
  } catch (error) {
    feedback(error.message);
  } finally {
    polling = false;
  }
}, 3000);
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
