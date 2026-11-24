# STAGE-017 · Первый реальный автономный пилот

Подготовка проверена частично в Linux. Сквозная приёмка ожидает разрешения владельца на использование включённой квоты, отдельного GitHub-репозитория с рабочим токеном, HTTPS в его приватной сети и постановки задачи с физического iPhone.

## PR #36 и staging

- На 24 ноября 2026 года PR #36 открыт. Проверенный HEAD `347ef675fbc8d1e26adb7b4ae780ac6c1e41dde9`, база `main@0c9198097f178e6e1d5b7bcb9a8a29bbc12ec7c4`. Локально прошли `git merge-tree --write-tree` и `git diff --check`. GitHub сообщает `mergeable: true` и `mergeable_state: unstable`. Список отправленных ревью пуст. Автослияние в метаданных репозитория отключено. [PR #36](https://github.com/TonyGoalsMan1/top-pariks/pull/36) · [Checks](https://github.com/TonyGoalsMan1/top-pariks/pull/36/checks)
- Все семь заданий на проверенном HEAD завершились успешно. TOP-PARIKS CI проверил ZIP, синтаксис и WooCommerce, включая аккаунт и AJAX-корзину в Chromium. Factory проверил жизненный цикл, изолированный сервер, оркестратор и HTTP/PWA с WebKit. [TOP-PARIKS CI #131](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/45337893002) · [Factory #39](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/45337892970)
- Активный ruleset `main` требует PR, разрешения обсуждений и трёх заданий TOP-PARIKS. Успешные результаты этих заданий видны в CI. Перед слиянием проверьте итоговый merge status в интерфейсе PR. При принятии стека сохраните ancestry через merge commit, как описано в STAGE-016. [Main Protection](https://github.com/TonyGoalsMan1/top-pariks/rules/27848018)
- На проверенной `main` файла `factory-staging.yml` ещё нет. В PR #36 он содержит `push: main`, который разрешает публикацию при `FACTORY_STAGING_ENABLED=true`. Не удалось прочитать действующее значение переменной, поэтому безопасность отдельного слияния #36 остаётся условной. Перед слиянием владелец сверяет, что флаг отсутствует или не равен `true`. В STAGE-017 удалён триггер `push`, оставлен ручной `workflow_dispatch` с прежним флагом. Другие staging-workflow в проверенном дереве запускаются вручную. [Actions Variables](https://github.com/TonyGoalsMan1/top-pariks/settings/variables/actions)

## Рабочий контур

- `factory.pilot` запускает панель и диспетчер из STAGE-016. Профиль генерирует локальный Git seed из зафиксированной темы и синтетического наполнения, заимствует закреплённые версии WordPress и WooCommerce и оставляет стенд на `127.0.0.1:8181`. Сценарий `setup --publish` создаёт новый приватный репозиторий и отправляет только базовый коммит. В нём одно задание GitHub Actions с `contents: read` для `factory/test-*`, без секретов и окружений развёртывания. Проверка разрешает изменение только `theme/top-pariks/style.css` и ограничивает размер файла.
- Адаптер `codex` использует официальный `codex exec` и существующий вход ChatGPT. Авторизацией управляет CLI. Запрос идёт из пустого временного каталога с read-only sandbox, отключёнными shell, web search, apps и плагинами, без GitHub, Docker и API-ключей в окружении. Модель возвращает предложение по JSON Schema, оркестратор применяет его только к разрешённому файлу. Существующий адаптер `responses` по-прежнему требует отдельного ключа, разрешения и денежного бюджета. [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode) · [Codex и план ChatGPT](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan) · [Лимиты использования](https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits)
- Цепочка из панели включает план, архитектурную сводку, изменение CSS, Git-коммит, открытие PR, CI и отдельный вызов QA. Оркестратор повторно сверяет HEAD открытого PR и выбранные проверки перед локальным развёртыванием. Закреплённая база и единственный изменённый CSS-файл проверяются перед сборкой. Factory делает снимок, устанавливает сборку из проверенного SHA, проверяет главную, каталог, товар, корзину и SHA-256 CSS по HTTP. Расхождение останавливает этап и запускает штатное восстановление. Результат содержит ссылку на открытый PR, SHA, CI, QA и подтверждение развёртывания.
- Профиль разрешает до шести вызовов в одном состоянии SQLite. Каждая попытка резервируется перед запуском CLI, полученные токены попадают в `ai_usage`. Стоимость ChatGPT CLI в долларах не выдаёт, поэтому отображается «сумма недоступна». Для сверки используются данные Usage в аккаунте владельца. GitHub Actions учитывает минуты отдельно. [Учёт ChatGPT](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans) · [Учёт GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## Действия владельца

Выполняйте из checkout ветки `codex/stage-017-real-pilot` на macOS или Ubuntu 24.04+, включая WSL2. Потребуются запущенный локальный Docker с Compose v2 и существующая приватная сеть между компьютером и iPhone. На WSL2 сетевой прокси должен иметь доступ к loopback-порту внутри WSL. Если PR #36 рассматривается к слиянию, сначала проверьте флаг staging и правила `main` из предыдущего раздела.

1. Подтвердите один пилот в пределах включённых лимитов Codex и Actions и разрешите локальное развёртывание проверенного CSS. Проверьте оставшуюся квоту и параметры автоматического пополнения. На GitHub используйте включённые минуты с нулевым допустимым перерасходом. Выполните установку, войдите в GitHub и проверьте вход Codex. При отсутствии входа ChatGPT вызовите ту же команду без `status` и войдите. GitHub CLI требует scope `workflow` для начальной записи файла workflow. [GitHub CLI auth refresh](https://cli.github.com/manual/gh_auth_refresh)

   ```bash
   bash scripts/factory-pilot-017.sh install
   gh auth login
   gh auth refresh -h github.com -s workflow
   bash scripts/factory-pilot-017.sh codex login status
   ```

2. Создайте свой отдельный приватный репозиторий командой ниже и задайте пароль PWA. Выдайте fine-grained PAT только новому репозиторию с `Contents: Read and write`, `Pull requests: Read and write`, `Checks: Read`. Введите его в локальном терминале. Запустите исходный WooCommerce ещё до постановки задачи. [GitHub fine-grained PAT](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

   ```bash
   bash scripts/factory-pilot-017.sh setup --publish \
     --repository TonyGoalsMan1/top-pariks-factory-pilot
   read -rsp 'Pilot GitHub token: ' FACTORY_GITHUB_TOKEN
   printf '\n'
   export FACTORY_GITHUB_TOKEN
   bash scripts/factory-pilot-017.sh baseline
   ```

3. Поднимите HTTPS только в приватной сети и разрешите доступ к панели для устройств владельца. Для имеющегося tailnet используйте Tailscale Serve. Он должен видеть порт `127.0.0.1:8787` в том же сетевом контуре. Подставьте показанный HTTPS-адрес целиком, без завершающего `/`. При использовании существующего reverse proxy сохраните исходные `Host` и `Origin` и выдайте доверенный iPhone сертификат. [Tailscale Serve](https://tailscale.com/kb/1312/serve)

   ```bash
   tailscale serve --bg http://127.0.0.1:8787
   export FACTORY_AUTHORIZE_CODEX_CHATGPT=1 FACTORY_AUTHORIZE_TEST_PREVIEW=1
   bash scripts/factory-pilot-017.sh run --origin 'https://ИМЯ-ИЗ-SERVE' --check
   bash scripts/factory-pilot-017.sh run --origin 'https://ИМЯ-ИЗ-SERVE'
   ```

4. С физического iPhone откройте адрес в Safari, проверьте доверенный HTTPS и добавьте PWA на экран «Домой». Убедитесь, что панель недоступна вне приватной сети. Войдите как `owner`, подключите `stage-017-store` и отправьте одну бизнес-задачу с ролью `frontend`. Для приёмки сохраните ID задачи, PR, SHA, статусы CI, итог Factory и сведения о расходе квоты. По окончании остановите launcher и отключите только созданный маршрут Serve.

   > Улучши карточки в каталоге и на странице тестового товара Atelier. Обнови типографику названия и цены, сделай кнопку добавления в корзину заметной, с областью нажатия от 44 px и видимым фокусом. Сохрани поведение корзины и читабельность без горизонтальной прокрутки на 375, 390, 768, 1024 и 1440 px. Используй только разрешённый CSS и существующую разметку. В отчёте укажи, что изменилось и что проверено.

## Предварительная проверка и приёмка

| Проверка | Результат |
| --- | --- |
| Установка, конфигурация и базовый стенд | Установщик и генератор прошли в Linux. Синтетический WordPress поднялся на закреплённых образах. Главная, каталог, товар и корзина прошли health. macOS и WSL2 ожидают проверки владельца. |
| Локальный этап развёртывания | Проверен вызовом штатного preview на вручную созданном изолированном коммите с CSS-комментарием. Factory развернула его, health и хеш CSS совпали. Чужая база отклонена. При намеренно неверном ожидаемом SHA-256 Factory восстановила предыдущую версию и закрыла журнал. Это проверка развёртывания отдельным шагом. |
| Codex ChatGPT | `codex-cli 0.172.0-alpha.2` подтвердил вход и наличие флагов структурированного запуска. Запросов к модели не было. |
| Регрессии | Прошли 26 базовых и 19 модульных тестов Factory, синтаксис Bash/JS и `git diff --check`. Обязательные команды CI тестового репозитория прошли локально. Сценарий совместимости STAGE-016 использовал существующий mock и не входит в приёмку пилота. |
| PWA и API | Локально проверены manifest, отказ при чужом Origin, Secure/HttpOnly cookie и отображение лимита вызовов у Codex-профиля. Этот тест проверяет HTTP-приложение с HTTPS origin за прокси. Реальный TLS-маршрут и Safari на iPhone ожидают владельца. |
| GitHub runtime | Локальный Git seed и workflow готовы. CLI среды получил `Forbidden`, GitHub-коннектор не создаёт репозитории, Cloud Desktop не открыл браузер. Удалённый репозиторий, токен, PR пилота и его CI ещё предстоит проверить. |
| Полный реальный цикл и оплата | Ожидает владельца. Не было вызовов модели, покупки услуг, публикации во внешний staging или слияния. |

При сбое развёртывания проверьте журнал Factory и результат отката перед возобновлением диспетчера. Используйте команды `get` и `events` из `factory.orchestrator` с теми же `--config` и `--state`. На физическом устройстве зафиксируйте постановку из Safari/PWA. На локальном WooCommerce сравните каталожную карточку и страницу товара до и после на пяти указанных ширинах. Среда CI проверяет состав изменения, а Factory подтверждает работу магазина и доставку CSS.
