# Listen — план публикации

> Документ-план: как вынести приложение в мир. Позиционирование, потенциал,
> репозиторий, сайт, лицензия, roadmap. Всё в одном месте, чтобы потом просто
> выполнять по пунктам.

---

## 0. Суть в одном абзаце

**Listen — это офлайн-диктовка для macOS. Нажал клавишу — поговорил — текст
появился в курсоре. Без облака, без аккаунта, без подписки, без телеметрии.
Меню-бар и одна клавиша — это весь интерфейс. Открытый код под MIT, модель под
пермиссивной лицензией. Сотни строк Python, которые можно прочитать за вечер.**

---

## 1. Потенциал: зачем это миру

### Рынок

Диктовка на Mac — категория, где доминируют **платные и облачные** решения.
Прямые конкуренты (состояние на 2026):

| Продукт | Модель | Цена | Облако | Открытый код |
|---|---|---|---|---|
| **Superwhisper** | подписка | ~$7.99/мес (~$80/год) | есть | нет |
| **MacWhisper** | разовая покупка | $99.99 | нет | нет |
| Apple Dictation (встроенная) | бесплатно | $0 | Enhanced — да | нет |
| whisper.cpp / CLI-инструменты | бесплатно | $0 | нет | да (но консоль) |
| **Listen** | бесплатно навсегда | $0 | **нет** | **да (MIT)** |

**Ниша Listen** — единственный прямоугольник, который никто не занимает:
*бесплатно + офлайн + нативный menu-bar UX + открытый код*. Superwhisper
собирает деньги за то, что модель и так бесплатна; MacWhisper берёт $100
разовой покупкой; whisper.cpp даёт движок, но не даёт «нажал-поговорил-готово».
Listen закрывает именно этот пробел: даёт **готовый продукт** с нулём трения и
нулём счёта.

### Почему это растёт само

- **On-device ASR — решённая открытая проблема.** Модели (Nemotron, Whisper)
  бесплатные, быстрые на Apple Silicon. Честной причины брать подписку за
  транскрипцию больше нет — это и есть главный нарратив.
- **Приватность как продукт, а не как оговорка.** «Аудио физически не может
  покинуть ваш Mac» — это не маркетинг, это архитектура (единственный сетевой
  участник — `127.0.0.1`). В эпоху, когда каждое приложение шлёт данные в
  облако, офлайн-по-умолчанию становится сильным конкурентным преимуществом.
- **Меню-бар — это UX, которого хотят, но не имеют.** Большинство диктовок —
  либо окно, либо Dock-иконка, либо подписочный сервис с onboarding. Listen —
  тихая утилита, которая живёт в строке меню и исчезает, когда не нужна.
- **Анти-подписочный настрой растёт.** Люди устали платить $8/мес за каждую
  утилиту. «It will never ask you for money» — это обещание, которое
  запоминается и пересылается друзьям.

### Кому это нужно

- Писатели, журналисты, студенты — быстрый черновик голосом.
- Люди с РСЯ/туннельным синдромом, для которых диктовка — не удобство, а
  необходимость (и платить $100 за доступность — несправедливо).
- Разработчики и технари, которые ценят приватность и читаемый код.
- Все, кто пишет на нескольких языках (авто-детект 40 локалей, включая
  русский и английский).
- Компании за файрволом / в регулируемых отраслях, где облако запрещено.

### Честная оценка потолка

Это **утилита**, а не платформа. Массовый хит уровня Raycast она не сделает, но
устойчивую нишу преданных пользователей — вполне. При правильной подаче
(сильное позиционирование приватности + бесплатно) — реалистично 5–20к
звёзд на GitHub за год-два и органический трафик через brew. Монетизации
здесь **не планируется и в том смысл**: ценность в том, что она бесплатна.

---

## 2. Позиционирование и маркетинговый язык

### Главная фраза (hero)

> **Press a key. Talk. Text appears. That is the whole app.**

### Три слова, которыми мы отличаемся

1. **Free, forever.** — никаких подписок, paywall, «pro»-тиров. Обещание
   вREADME, которое мы держим архитектурно: в коде нет ни платёжного SDK, ни
   телеметрии, ни сервера аналитики. Это нельзя «включить» позже — нечего
   включать.
2. **Offline.** — аудио не покидает ваш Mac. Приватность как архитектура.
3. **Yours.** — открытый код под MIT. Сотни строк, которые читаются за вечер.

### Тон

Тихий, уверенный, без капс-лока и без восклицаний. Как само приложение:
минимум слов, максимум смысла. Не «РУШИМ ИНДУСТРИЮ ПОДПИСОК», а
«dictation should be a quiet utility that belongs to you, not a recurring
bill». Противопоставление делается спокойно — пусть конкуренты сами выглядят
дорого на нашем фоне.

### Маркетинговые тезисы (готовые для сайта/README)

- **One job.** Recognize speech and type it. Two settings, zero windows.
- **It will never ask you for money.** No paywall, no «pro» tier, no
  future bait-and-switch.
- **Your audio never leaves your Mac.** The only network address Listen ever
  talks to is `127.0.0.1`.
- **A menu-bar icon and a single key. No dock, no onboarding, no account.**
- **A few hundred lines of Python you can read in one sitting.** If you
  don’t trust a closed app with your microphone, here you don’t have to.
- **Works on a plane, in a basement, behind a firewall, forever.** The model
  downloads once (707 MB) and lives on your disk.

### «Особое удовольствие» — как это сформулировать

Главная эмоция, которую продаём: **удовольствие от инструмента, который делает
одну вещь идеально, а потом уходит с дороги.**

> Most dictation apps want to be a platform — a window, a dock icon, an
> account, a subscription, a brand. Listen wants to be invisible. You press a
> key, you talk, text lands where your cursor was. Then it’s gone. No
> notifications, no telemetry, no upsell. Just a quiet utility that belongs to
> you, the way `cp` and `pbpaste` belong to you. That’s the whole point.

Это и есть настоящий open-source дух: **инструмент, который принадлежит тебе,
а не сервис, который тебя арендует.**

---

## 3. GitHub-репозиторий

### Имя и адрес

- `github.com/valentyn/listen` (как уже в README). Короткое, читаемое, совпадает
  с `brew tap valentyn/listen`. Не добавлять `-app` / `-mac` суффиксы — короче
  лучше.

### Структура (что добавить к существующему)

```
listen/
├── README.md              # полировать (см. §6)
├── LICENSE                # НОВОЕ — MIT (см. §5)
├── NOTICE                 # НОВОЕ — про лицензию модели OpenMDW-1.1
├── CONTRIBUTING.md        # НОВОЕ — как собрать, как тестировать, стиль кода
├── CODE_OF_CONDUCT.md     # НОВОЕ — Contributor Covenant
├── SECURITY.md            # НОВОЕ — куда слать уязвимости (приватно)
├── CHANGELOG.md           # НОВОЕ — Keep a Changelog
├── publish.md             # этот документ (после запуска можно оставить как ADR или убрать)
├── .github/
│   ├── workflows/ci.yml   # НОВОЕ — pytest на push/PR
│   ├── workflows/release.yml # НОВОЕ — сборка .app + GitHub Release по тегу
│   ├── ISSUE_TEMPLATE/    # НОВОЕ — bug / feature шаблоны
│   └── FUNDING.yml        # НОВОЕ (опц.) — GitHub Sponsors, если захочешь
├── screenshots/           # уже есть — добавить в README
├── listen/ …              # код
└── tests/ …
```

### Topics на репозитории

`macos`, `speech-to-text`, `dictation`, `offline`, `privacy`, `asr`,
`menu-bar`, `pyobjc`, `open-source`, `no-subscription`, `nemotron`,
`accessibility`.

### CI / release

- **ci.yml**: `.venv/bin/python -m pytest -q` на macOS runner (нужен PyObjC,
  тесты логики кросс-платформенные, но импорт AppKit требует mac). Плюс
  `python -m compileall listen`.
- **release.yml**: по тегу `v*` — `setup_app.py py2app`, упаковать
  `dist/Listen.app` в zip, прикрепить к GitHub Release, обновить cask-формулу
  (PR в `homebrew-listen`).

### Issue-шаблоны

- **Bug**: версия macOS, версия Listen, шаги, ожидание/факт, лог
  (`~/Library/Logs/listen.log`), выданы ли Accessibility/Microphone.
- **Feature**: use case одной фразой, текущий workaround.

### Первые issues «good first issue»

Чтобы репозиторий выглядел живым и приглашал:
1. «Add a Linux build (the model + engine are cross-platform; PyObjC is not).»
2. «Add a Setting to choose the model (Whisper vs Nemotron).»
3. «Internationalize the menu UI (currently English-only).»
4. «Add a downloadable .dmg alongside the zip.»

### README-полировка (см. §6)

Добавить: бейджи (CI, license, brew), GIF/скриншот меню-бара, секцию
«Privacy» одним абзацем, ссылку на сайт.

---

## 4. Сайт

### Где хостить

- **GitHub Pages** — бесплатно, рядом с репо, `CNAME` для своего домена.
- Свой домен (опционально, позже):候选 — `listendictate.app`,
  `listen.cool`, `getlisten.app`, `listen.sh`. Зарезервировать хотя бы один,
  когда пойдёт трафик; до этого — `valentyn.github.io/listen` работает.

### Структура (одна длинная landing, без роутинга)

1. **Hero** — фраза `Press a key. Talk. Text appears.` + одна строка под
   (`Free, offline speech-to-text for macOS.`) + кнопки:
   `Download for Mac` (→ GitHub Release) и `View source` (→ GitHub).
2. **3-секундное демо** — короткая GIF/видео: нажал → говорил → текст в Notes.
   Это продаёт больше любого текста.
3. **Why Listen** — 3 карточки: `Free, forever` / `Offline by design` /
   `Yours (MIT)`. По одному тезису из §2 на каждую.
4. **How it works** — 3 шага (Press / Talk / Done) + одна фраза про меню.
5. **Privacy** — один честный абзац про `127.0.0.1`, отсутствие телеметрии и
   читаемый код. Это раздел, ради которого приходят.
6. **Install** — brew-команда в code-блоке + «or build from source».
7. **FAQ** — короткие ответы: «Does it send audio anywhere? No.»,
   «Which languages? Auto-detect 40 locales, pin 19.»,
   «Does it work offline? Yes, after the one-time model download.»,
   «Will it ever cost money? No.»
8. **Footer** — MIT license, ссылка на GitHub, год. Без аналитики на сайте
   (в том же духе, что и приложение).

### Дизайн-принципы сайта = принципы приложения

- Минимум слов, максимум воздуха.
- Один акцентный цвет (монохром + один), sans-serif, без градиентов и неона.
- Никаких pop-up, cookie-баннеров, форм подписки. Тихий сайт про тихую утилиту.
- Тёмная тема по умолчанию (соответствует menu-bar-эстетике), light по
  `prefers-color-scheme`.
- Текст сайта — на английском (глобальная аудитория); можно позже добавить ru.

### Готовый копирайт (английский, вставлять в HTML)

```
Hero headline:    Press a key. Talk. Text appears.
Hero sub:         Free, offline speech-to-text for macOS. No cloud, no
                  account, no subscription.
CTA primary:      Download for Mac
CTA secondary:    View source

Card 1 title:     Free, forever
Card 1 body:       No paywall, no «pro» tier, no future bait-and-switch. The
                  code has no payment SDK and no telemetry — there is nothing
                  to switch on.

Card 2 title:      Offline by design
Card 2 body:       Your audio never leaves your Mac. The only network address
                  Listen ever talks to is 127.0.0.1. It works on a plane, in a
                  basement, behind a firewall.

Card 3 title:      Yours
Card 3 body:       Open source under MIT. A few hundred lines of Python you
                  can read in one sitting. If you don’t trust a closed app
                  with your microphone, here you don’t have to.

Privacy heading:  Your voice stays on your Mac
Privacy body:     Listen never uploads anything. Audio is captured to memory,
                  transcribed by a local model, and pasted at your cursor. The
                  transcription server binds to 127.0.0.1 and is invisible
                  outside your machine. No account, no analytics, no cloud. The
                  source is short enough to verify that yourself.

FAQ Q1:           Does it send my audio anywhere?
FAQ A1:           No. Audio is processed locally and never leaves your Mac.
FAQ Q2:           Will it ever cost money?
FAQ A2:           No. There is nothing in the code to charge for, by design.
FAQ Q3:           Which languages?
FAQ A3:           Auto-detect across 40 locales (Russian, English, and more).
                  You can also pin one of 19 transcription-ready locales.
FAQ Q4:           Does it need the internet?
FAQ A4:           Only once — to download the model (707 MB). After that, fully
                  offline.
```

---

## 5. Лицензия

### Код — MIT

Добавить файл `LICENSE` со стандартным MIT-текстом (год — 2026, владелец —
Valentyn). MIT выбран осознанно: самый пермиссивный, самый узнаваемый, ноль
трения для тех, кто хочет форкать и встраивать. Это согласуется с обещанием
«Yours» и с тоном проекта.

### Модель — OpenMDW-1.1

Модель `nvidia/nemotron-3.5-asr-streaming-0.6b` — **не** LLM, это ASR-модель
(распознавание речи), 600M параметров, 40 локалей, авто-детект. Лицензия —
**OpenMDW-1.1** (Open Model Development Agreement), пермиссивная:

- ✅ коммерческое использование,
- ✅ создание и распространение деривативов (fine-tune и т.д.),
- ✅ нет претензий на выходные данные.

Это значит: **да, ты имеешь право распространять модель вместе с приложением
и использовать его свободно**, включая коммерчески — если соблюдаешь условия
OpenMDW-1.1 (сохранить уведомление о лицензии). Движок NeMo-Speech.cpp —
свой лицензионный файл; проверить его LICENSE в `listen/resources/nemo-speech/`
и процитировать в `NOTICE`.

### Про «использовать LLM в проекте»

Ты написал «ведь я же могу использовать LLM в своём проекте» — два момента,
чтобы не было путаницы:

1. **Сейчас в проекте нет LLM.** Есть ASR-модель (превращает речь в текст). Это
   принципиально другой класс моделей, и его лицензия (OpenMDW-1.1) permits
   всё, что нужно.
2. **Если захочешь добавить LLM** (например, для пост-обработки текста:
   пунктуация, форматирование, исправление, команды «new paragraph») — это
   законно и лицензия позволяет. Но есть архитектурный выбор:

   - **Локальная LLM** (маленькая on-device модель, например через
     `mlx-lm` / `llama.cpp`) — сохраняет главное обещание: офлайн и приватно.
     Рекомендуемый путь, если добавлять. Чуть больше RAM/батарея.
   - **Облачная LLM** (OpenAI и т.п.) — убивает ровно то, что продаём
     (приватность, офлайн, «никакого облака»). Не рекомендую как дефолт;
     если очень хочется — только как опция, по умолчанию выключенная и с
     явным согласием пользователя.

   Совет: держи LLM-функции **необязательными и офлайн-first**, иначе
   маркетинговое обещание «your audio never leaves your Mac» перестанет быть
   буквальным.

### Файл `NOTICE` (черновик)

```
Listen
Copyright (c) 2026 Valentyn
Licensed under the MIT License (see LICENSE).

Bundled model: nvidia/nemotron-3.5-asr-streaming-0.6b
Licensed under the OpenMDW-1.1 license — https://openmdw.ai/license/1-1/
Commercial use, modification, and redistribution permitted under its terms.

Bundled engine: NeMo-Speech.cpp (NVIDIA)
See listen/resources/nemo-speech/LICENSE for engine terms.
```

---

## 6. README — что поменять перед публикацией

- [ ] Добавить бейджи: CI status, MIT license, `brew install --cask listen`.
- [ ] Добавить скриншот/GIF меню-бар-иконки вверху (из `screenshots/`).
- [ ] Секция **Privacy** — один абзац про `127.0.0.1` (взять из §4).
- [ ] Поправить счётчик локалей: после удаления broad-группы — **авто-детект
      40 локалей, закрепить 19 transcription-ready** (README сейчас говорит
      «pin 32 locales» — устарело).
- [ ] Ссылка на сайт (когда будет).
- [ ] Секция **Acknowledgements** — NVIDIA Nemotron + NeMo-Speech.cpp.
- [ ] Убрать/перенести `publish.md` и внутренние `refactoring.md`/`Q-A.md`
      в `docs/`, чтобы корень репо был чистым для публики.

---

## 7. Чек-лист запуска (порядок действий)

1. **Лицензия и документы**
   - [ ] Создать `LICENSE` (MIT).
   - [ ] Создать `NOTICE` (модель OpenMDW-1.1 + движок).
   - [ ] Проверить LICENSE движка в `resources/nemo-speech/`.
   - [ ] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`.
2. **GitHub**
   - [ ] Создать публичный репо `valentyn/listen`.
   - [ ] `.github/workflows/ci.yml` (pytest) + `release.yml` (build .app).
   - [ ] Topics, описание, ссылка на сайт.
   - [ ] Issue-шаблоны, пары `good first issue`.
3. **Подпись и релиз**
   - [ ] Настроить code signing + notarization (сейчас #1 риск — без него
         Accessibility-грант сбрасывается при каждом пересборке, что больно
         для пользователей). См. `listen-refactoring-status`.
   - [ ] Собрать подписанный `.app`, прикрепить к первому GitHub Release.
   - [ ] Обновить/создать cask в `homebrew-listen`.
4. **Сайт**
   - [ ] Одностраничник на GitHub Pages (копирайт готов в §4).
   - [ ] GIF-демо 3 секунды.
   - [ ] (опц.) свой домен.
5. **Анонс**
   - [ ] Hacker News (Show HN: «Listen — free, offline speech-to-text for
         macOS, MIT»). Акцент: приватность + бесплатно + открытый код.
   - [ ] r/macapps, r/osx,lobsters, Product Hunt.
   - [ ] Твит/X одним абзацем + GIF.
   - [ ] Короткий пост на русском (Хабр — аудитория ценит приватность).

---

## 8. Roadmap (что говорить «дальше»)

Публиковать честный, короткий roadmap — показывает, что проект жив, без
обещанийfeatures-as-locked-roadmap:

- **v0.3** — подписанный + notarized билд (стабильный Accessibility-грант).
- **v0.4** — выбор модели (Nemotron / Whisper-medium), чтоб пользователь сам
 权衡ил качество/размер.
- **v0.5** — опциональная офлайн LLM-постобработка (пунктуация,
  переформатирование) через локальную модель, по умолчанию выключено.
- **Будущее** — Linux-сборка (движок кросс-платформенный, нужен не-PyObjC
  UI), настраиваемые команды голосом, синхронизация словаря.

---

## 9. Чего мы принципиально не делаем

Это тоже часть позиционирования — сказать «нет» громче, чем конкуренты
говорят «да»:

- **Нет подписки. Никогда.** Нет payment SDK, нет телеметрии, нет сервера
  лицензий — нечем «включить» позже.
- **Нет облака для аудио.** Единственный сетевой адрес — `127.0.0.1`.
- **Нет аккаунта.** Не нужен.
- **Нет телеметрии/аналитики.** Даже на сайте.
- **Нет Dock-иконки, нет онбординга, нет окон** (кроме однократного
  скачивания модели).

Каждое «нет» — это пункт, который можно повесить на сайт и в README. В сумме
они говорят громче любого feature-листа.

---

## 10. Итог одним абзацем

Listen занимает пустой прямоугольник на рынке диктовок: **бесплатно +
офлайн + нативный menu-bar + открытый код**. Главный нарратив — «on-device
ASR — решённая открытая проблема; честной причины брать подписку больше нет».
План запуска: MIT-лицензия + файлы сообщества → публичный GitHub с CI и
авто-релизами → одностраничный тихий сайт на GitHub Pages → подписанный билд
через brew → анонс в HN/reddit с акцентом на приватность и «never asks you for
money». Дальше — жить по roadmap, держа обещание офлайн-first.