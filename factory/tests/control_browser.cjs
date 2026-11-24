'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium, webkit, devices } = require('playwright-core');

const [origin, password] = process.argv.slice(2);
const output = process.env.FACTORY_BROWSER_ARTIFACTS;

async function layout(page, width) {
  await page.setViewportSize({ width, height: 850 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'Horizontal overflow at ' + width + ' px');
}

async function login(page, user) {
  await page.goto(origin);
  await page.getByLabel('Логин', { exact: true }).fill(user);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.locator('#project-title').waitFor({ state: 'visible' });
}

async function exercise(browser, device, name) {
  const context = await browser.newContext(device);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', async (dialog) => {
    errors.push(dialog.message());
    await dialog.dismiss();
  });
  try {
    await login(page, 'owner');
    await page.getByRole('heading', { name: 'alpha', exact: true }).waitFor();
    assert(await page.locator('#executor').textContent() === 'Демонстрация · Mock');
    if (name === 'webkit-iphone') {
      assert(await page.evaluate(() => /iPhone/.test(navigator.userAgent) && innerWidth === 390));
      await layout(page, 375);
      await layout(page, 390);
    } else {
      for (const width of [375, 390, 768, 1024, 1440]) await layout(page, width);
    }
    await page.getByRole('button', { name: 'Остановить очередь', exact: true }).click();
    await page.getByRole('button', { name: 'Возобновить очередь', exact: true }).waitFor();
    const objective = 'Проверить каталог ' + name + ' <img src=x onerror=alert(1)>';
    await page.getByLabel('Что нужно сделать?').fill(objective);
    await page.getByRole('button', { name: 'Добавить в очередь' }).click();
    await page.locator('#task-detail').getByRole('heading', { name: objective, exact: true }).waitFor();
    const apiList = await (await context.request.get(origin + '/api/v1/projects/alpha')).json();
    const tasks = apiList.tasks.filter((task) => task.spec.objective === objective);
    assert.equal(tasks.length, 3);
    assert(tasks.every((task) => task.status === 'queued'), 'Pause did not reach the worker');
    assert.equal(await page.locator('#task-detail img').count(), 0, 'Objective was rendered as markup');

    await page.getByRole('button', { name: 'Остановить задачу', exact: true }).click();
    await page.getByRole('button', { name: 'Возобновить задачу', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Отменить задачу', exact: true }).click();
    await page.getByRole('button', { name: 'Повторить задачу', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Возобновить очередь', exact: true }).click();
    const codeTask = tasks.find((task) => task.spec.operation === 'code');
    await page.waitForFunction(async (id) => {
      const response = await fetch('/api/v1/projects/alpha/tasks/' + id);
      return (await response.json()).status === 'done';
    }, codeTask.dependencies[0]);
    await page.getByRole('button', { name: 'Повторить задачу', exact: true }).click();
    await page.locator('#task-detail').getByText('Mock file proposal', { exact: true }).waitFor();
    await page.locator('#task-detail').getByText('CI · git diff --check', { exact: true }).waitFor();
    await page.locator('#task-detail summary').click();
    await page.locator('#task-detail').getByText('Этап начат', { exact: true }).first().waitFor();

    if (process.env.FACTORY_WORDPRESS_TEST === '1') {
      await page.getByLabel('Операция', { exact: true }).selectOption('backup');
      await page.getByRole('button', { name: 'Поставить операцию в очередь' }).click();
      await page.getByText('Ждёт разрешения', { exact: true }).first().waitFor();
      await page.getByRole('checkbox', { name: /Подтверждаю.*Создать копию/ }).check();
      await page.getByRole('button', { name: 'Разрешить действие' }).click();
      await page.locator('#task-detail').getByText(/[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}/).waitFor({
        timeout: 120000,
      });
    }

    await page.waitForFunction(async () => Boolean((await navigator.serviceWorker.ready).active));
    const cacheKeys = await page.evaluate(async () => {
      const names = await caches.keys();
      const requests = await Promise.all(names.map(async (cache) => (await caches.open(cache)).keys()));
      return requests.flat().map((request) => new URL(request.url).pathname);
    });
    assert(cacheKeys.includes('/manifest.webmanifest') && cacheKeys.every((url) => !url.startsWith('/api/')),
      'PWA cache is missing the shell or contains API data');
    if (output) {
      await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
      if (name === 'chromium-desktop') {
        await layout(page, 390);
        await page.screenshot({ path: path.join(output, 'chromium-390.png'), fullPage: true });
      }
    }
    await page.getByLabel('Проект', { exact: true }).selectOption('beta');
    await page.getByRole('heading', { name: 'beta', exact: true }).waitFor();
    assert.equal(await page.getByText(objective, { exact: true }).count(), 0, 'Foreign task leaked');
    await page.getByRole('button', { name: 'Выйти', exact: true }).click();
    await page.getByRole('heading', { name: 'Вход в панель' }).waitFor();
    assert.equal(await page.getByText(objective, { exact: true }).count(), 0, 'Task remained in the DOM after logout');
    await login(page, 'viewer');
    await page.getByRole('heading', { name: 'beta', exact: true }).waitFor();
    assert(!await page.getByRole('button', { name: 'Добавить в очередь' }).isVisible());
    assert.equal(await page.getByLabel('Проект', { exact: true }).locator('option').count(), 1);
    assert.deepEqual(errors, []);
    console.log('Browser integration passed: ' + name);
  } finally {
    await context.close();
  }
}

async function main() {
  const engines = [
    [chromium, {}, 'chromium-desktop', process.env.FACTORY_CHROMIUM_PATH],
    [webkit, devices['iPhone 13'], 'webkit-iphone', undefined],
  ];
  for (const [engine, device, name, executablePath] of engines) {
    if (process.env.FACTORY_BROWSER_ONLY && process.env.FACTORY_BROWSER_ONLY !== name) continue;
    const browser = await engine.launch({ executablePath });
    try {
      await exercise(browser, device, name);
    } finally {
      await browser.close();
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
