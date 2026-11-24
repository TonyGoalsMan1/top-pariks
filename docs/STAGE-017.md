# STAGE-017 · Первый реальный автономный пилот

Подготовка проверена частично в Linux. Сквозная приёмка ожидает разрешения владельца на использование включённой квоты, отдельного GitHub-репозитория с рабочим токеном, HTTPS в его приватной сети и постановки задачи с физического iPhone.

## Cloud Pilot с iPhone

### Первый вход

1. Войдите в GitHub в Safari и проверьте остаток **compute и storage**. Без платёжного метода GitHub останавливает Codespaces при исчерпании включённого лимита. При сохранённом платёжном методе убедитесь, что для Codespaces установлен бюджет `$0` с **Stop usage when budget limit is reached**. Для первого сеанса выставьте таймаут 10 минут и оставьте стандартное хранение 30 дней. [Расход](https://github.com/settings/billing/usage) · [Бюджеты](https://github.com/settings/billing/budgets) · [Таймаут](https://github.com/settings/codespaces)
2. Откройте ветку облачного пилота в Codespaces, выберите самую маленькую машину **2 cores** и нажмите **Create codespace**. Веб-редактор и терминал открываются в Safari. Devcontainer установит Docker с Compose v2 и Codex CLI, подготовит синтетический магазин и запустит панель. [Создать или возобновить Codespace](https://codespaces.new/TonyGoalsMan1/top-pariks/tree/codex/stage-017-cloud-pilot?quickstart=1)
3. В VS Code Web выберите **☰ → Terminal → Run Task… → Factory: Open pilot panel**. Задача запустит панель и покажет в терминале её HTTPS-ссылку, логин `owner` и пароль. В **Ports** порт `8787` должен быть **Private**, с протоколом **HTTP** от туннеля к приложению. Откройте ссылку отдельной вкладкой Safari, войдите и нажмите «Подключить» для `stage-017-store`. Успешный вход и загрузка проекта проверят фактический маршрут GitHub, включая Host, Origin и передачу cookie. Проверку **Поделиться → На экран «Домой»** проведите отдельно. Если оболочка PWA запрашивает авторизацию GitHub повторно, используйте Safari. [Приватные порты](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces#port-forwarding)

### Исправление прав в существующем Codespace

1. Откройте существующий Codespace в Safari. На ветке `codex/stage-017-cloud-pilot` выберите **Source Control → … → Pull**. [Обновление ветки в VS Code Web](https://docs.github.com/en/codespaces/developing-in-a-codespace/using-source-control-in-your-codespace#pulling-changes-from-the-remote-repository)
2. Выберите **☰ → Terminal → Run Task… → Factory: Open pilot panel**. Задача исправит права и откроет доступ к панели в текущем контейнере. [Задачи VS Code](https://code.visualstudio.com/docs/debugtest/tasks)

Установщик выставляет `0700`, сохраняет данные оператора и передаёт оператору пустой каталог, созданный от root. Если каталог содержит файлы и принадлежит root либо доступен другим на запись, запуск остановится с диагностикой, сохранив содержимое.

При остановке запуска команда укажет на `/workspaces/.factory-pilot-017/start.log`. После устранения причины повторите `bash .devcontainer/pilot.sh start`, затем `access`. Если GitHub показывает ошибку прокси или приложение отвечает «Неизвестный адрес панели», проверьте приватный порт и запишите HTTP-статус. Панель принимает точный Host из выведенной ссылки и точный Origin на POST, а сессия использует `__Host-factory-session` с `Secure; HttpOnly; SameSite=Strict; Path=/`. Сохраните этот режим при диагностике.

### Подготовка запуска задачи после первого входа

Панель и WooCommerce доступны до авторизации Codex и создания GitHub-репозитория. WooCommerce слушает только loopback на `8181`, и через Codespaces перенаправляется только PWA на `8787`. Панель блокирует новые задания и повторный запуск при выключенном диспетчере.

1. Авторизуйте Codex существующим аккаунтом ChatGPT. При необходимости включите **Device code authentication for Codex** в настройках безопасности ChatGPT. Запустите команду, откройте указанный CLI адрес в Safari, подтвердите одноразовый код и проверьте сообщение `Logged in using ChatGPT`. Этот шаг не выполняет запрос модели. [Настройки ChatGPT](https://chatgpt.com/#settings/Security) · [Codex Authentication](https://learn.chatgpt.com/docs/auth?surface=cli)

   ```bash
   bash .devcontainer/pilot.sh login
   ```

2. Штатный установщик создаёт отдельный приватный `TonyGoalsMan1/top-pariks-factory-pilot` и отправляет туда только синтетический seed с ограниченным workflow. Для этого GitHub CLI один раз запрашивает согласие через Safari. Встроенный токен Codespaces ограничен исходным репозиторием. После публикации завершите широкую CLI-сессию и создайте fine-grained PAT с коротким сроком действия, выбрав только новый репозиторий. Разрешения — **Contents: Read and write**, **Pull requests: Read and write**, **Checks: Read**. [Тестовый репозиторий после создания](https://github.com/TonyGoalsMan1/top-pariks-factory-pilot) · [Создать fine-grained PAT](https://github.com/settings/personal-access-tokens/new)

   ```bash
   env -u GH_TOKEN -u GITHUB_TOKEN gh auth login -h github.com --web --git-protocol https --scopes workflow
   bash .devcontainer/pilot.sh publish
   env -u GH_TOKEN -u GITHUB_TOKEN gh auth logout -h github.com -u TonyGoalsMan1
   ```

3. Только после явного разрешения владельца на расход включённой квоты Codex и локальное развёртывание проверьте остаток ChatGPT, отключённое автопополнение и остаток минут приватных Actions с защитой от перерасхода. Команда запросит PAT в скрытом вводе, проверит авторизацию и приватный репозиторий, затем запустит диспетчер в терминале. Оставьте Codespace работающим, перейдите в панель и поставьте одну задачу из раздела ниже. По окончании остановите диспетчер через `Ctrl+C`, а затем сам Codespace. После остановки среды диспетчер включается только этой командой. [Использование GitHub](https://github.com/settings/billing/usage) · [Использование Codex](https://chatgpt.com/codex/settings/usage)

   ```bash
   FACTORY_AUTHORIZE_CODEX_CHATGPT=1 FACTORY_AUTHORIZE_TEST_PREVIEW=1 bash .devcontainer/pilot.sh dispatch
   ```

### Квота и состояние

- Персональный GitHub Free включает 120 core-hours и 15 GB-month в месяц. Pro включает 180 core-hours и 20 GB-month. На машине с 2 ядрами это до 60 или 90 часов работы при полном остатке compute. Хранилище учитывается и на остановленной машине. У аккаунта владельца нужно отдельно подтвердить текущий остаток и защиту от перерасхода. [Codespaces Billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces)
- Закрытие Safari не останавливает среду. На странице Codespaces используйте **… → Stop codespace**. При простое GitHub по умолчанию останавливает её через 30 минут, а остановленную среду по умолчанию удаляет спустя 30 дней. Ссылка панели недоступна после остановки до возобновления Codespace. GitHub запрашивает повторную авторизацию приватного порта после истечения его cookie, обычно через три часа. [Codespace lifecycle](https://docs.github.com/en/codespaces/about-codespaces/understanding-the-codespace-lifecycle) · [Остановить или открыть](https://github.com/codespaces)
- При обычном Stop/Resume сохраняются SQLite, настройки, пароль и CODEX_HOME в `/workspaces/.factory-pilot-017`, а данные WordPress/MariaDB остаются в томах внутреннего Docker. Сессия панели создаётся заново. Файлы в `/workspaces` рассчитаны на сохранение при rebuild. Перед **Full Rebuild** сделайте штатную резервную копию WordPress и сохраните её вне Docker: cache и Docker volumes могут быть очищены. Удаление Codespace удаляет его локальное состояние. При незавершённой операции выполните восстановление из раздела ниже перед запуском диспетчера. [Rebuild и volumes](https://docs.github.com/en/codespaces/developing-in-a-codespace/rebuilding-the-container-in-a-codespace)

### Статус проверки и запасной путь

Codespaces поддерживает требуемый devcontainer и приватный проброс порта. Сквозной запуск на аккаунте владельца ожидает проверки остатка квоты. В рабочей Cloud-среде GitHub CLI получил `Forbidden` на запросы профиля и списка Codespaces, доступ к странице биллинга из облачного браузера не открылся. GitHub-коннектор позволяет обновлять исходную ветку и PR, но не показывает биллинг, не создаёт Codespaces и не создаёт новый репозиторий. Сборка devcontainer в этой Cloud-среде остановилась на загрузке базового образа MCR. Это наблюдение относится к сети текущей среды.

Локально установщик дважды поднял один синтетический WooCommerce с проверкой главной, каталога, товара и корзины. Прошли 45 unit-тестов и сценарий API/очереди с mock-исполнителем. Протестированы HTTPS с сертификатом для тестового `*.app.github.dev`-имени, точные Host/Origin, cookie, доступ с сессией, manifest и service worker, подключение проекта и запрет постановки задания без диспетчера. Приватный шлюз GitHub, Stop/Resume на GitHub и Safari на физическом iPhone проверяются первым сеансом владельца.

Если исчерпан остаток, дождитесь сброса квоты без увеличения бюджета. Если GitHub подтвердит техническую блокировку Codespaces для аккаунта или недоступность приватного порта, минимальный перенос — существующий Linux Docker-хост с авторизованным приватным Tailscale Serve, используя прежний сценарий ниже. Для текущей Cloud-среды настроен только SSH-порт, поэтому готового приватного HTTPS-адреса на ней нет. [Tailscale Serve](https://tailscale.com/kb/1312/serve)

## PR #36 и staging

- На 24 ноября 2026 года PR #36 открыт. Проверенный HEAD `347ef675fbc8d1e26adb7b4ae780ac6c1e41dde9`, база `main@0c9198097f178e6e1d5b7bcb9a8a29bbc12ec7c4`. Локально прошли `git merge-tree --write-tree` и `git diff --check`. GitHub сообщает `mergeable: true` и `mergeable_state: unstable`. Список отправленных ревью пуст. Автослияние в метаданных репозитория отключено. [PR #36](https://github.com/TonyGoalsMan1/top-pariks/pull/36) · [Checks](https://github.com/TonyGoalsMan1/top-pariks/pull/36/checks)
- Все семь заданий двух запусков с событием `pull_request` завершились успешно. TOP-PARIKS CI проверил ZIP, синтаксис и WooCommerce, включая аккаунт и AJAX-корзину в Chromium. Factory проверил жизненный цикл, изолированный сервер, оркестратор и HTTP/PWA с WebKit. В отдельном запуске Factory по `push` того же SHA серверный сценарий упал на SSH forwarding, а задание PWA было отменено. [TOP-PARIKS CI #131](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/45337893002) · [Factory #39 по PR](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/45337892970) · [Factory по push](https://github.com/TonyGoalsMan1/top-pariks/actions/runs/45337883074)
- Активный ruleset `main` требует PR, разрешения обсуждений и трёх заданий TOP-PARIKS. Успешные результаты этих заданий видны в CI. Перед слиянием проверьте итоговый merge status в интерфейсе PR. При принятии стека сохраните ancestry через merge commit, как описано в STAGE-016. [Main Protection](https://github.com/TonyGoalsMan1/top-pariks/rules/27848018)
- На проверенной `main` файла `factory-staging.yml` ещё нет. В PR #36 он содержит `push: main`, который разрешает публикацию при `FACTORY_STAGING_ENABLED=true`. Не удалось прочитать действующее значение переменной, поэтому безопасность отдельного слияния #36 остаётся условной. Перед слиянием владелец сверяет, что флаг отсутствует или не равен `true`. В STAGE-017 удалён триггер `push`, оставлен ручной `workflow_dispatch` с прежним флагом. Другие staging-workflow в проверенном дереве запускаются вручную. [Actions Variables](https://github.com/TonyGoalsMan1/top-pariks/settings/variables/actions)

## Рабочий контур

- `factory.pilot` запускает панель и диспетчер из STAGE-016. Профиль генерирует локальный Git seed из зафиксированной темы и синтетического наполнения, заимствует закреплённые версии WordPress и WooCommerce и оставляет стенд на `127.0.0.1:8181`. Сценарий `setup --publish` создаёт новый приватный репозиторий и отправляет только базовый коммит. В нём одно задание GitHub Actions с `contents: read` для `factory/test-*`, без секретов и окружений развёртывания. Проверка разрешает изменение только `theme/top-pariks/style.css` и ограничивает размер файла.
- Адаптер `codex` использует официальный `codex exec` и существующий вход ChatGPT. Авторизацией управляет CLI. Запрос идёт из пустого временного каталога с read-only sandbox, отключёнными shell, web search, apps и плагинами, без GitHub, Docker и API-ключей в окружении. Модель возвращает предложение по JSON Schema, оркестратор применяет его только к разрешённому файлу. Существующий адаптер `responses` по-прежнему требует отдельного ключа, разрешения и денежного бюджета. [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode) · [Codex и план ChatGPT](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan) · [Лимиты использования](https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits)
- Цепочка из панели включает план, архитектурную сводку, изменение CSS, Git-коммит, открытие PR, CI и отдельный вызов QA. Оркестратор повторно сверяет HEAD открытого PR и выбранные проверки перед локальным развёртыванием. Закреплённая база и единственный изменённый CSS-файл проверяются перед сборкой. Factory делает снимок, устанавливает сборку из проверенного SHA, проверяет главную, каталог, товар, корзину и SHA-256 CSS по HTTP. Расхождение останавливает этап и запускает штатное восстановление. Результат содержит ссылку на открытый PR, SHA, CI, QA и подтверждение развёртывания.
- Профиль разрешает до шести вызовов в одном состоянии SQLite. Каждая попытка резервируется перед запуском CLI, полученные токены попадают в `ai_usage`. Стоимость ChatGPT CLI в долларах не выдаёт, поэтому отображается «сумма недоступна». Для сверки используются данные Usage в аккаунте владельца. GitHub Actions учитывает минуты отдельно. [Учёт ChatGPT](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans) · [Учёт GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

## Действия владельца на отдельном Linux или macOS хосте

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
