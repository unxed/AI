# AI: скиллы оффлоадинга

Скиллы для агента. Дешёвый роутер передаёт задачу модели через её веб-чат. Вся работа с моделью идёт во встроенном браузере Claude (`mcp__Claude_Browser__*`), в собственной вкладке агента. Консольных клиентов нет.

| Скилл | Модель |
|---|---|
| [`OPERATOR.md`](OPERATOR.md) | оператор: несколько роутеров параллельно |
| [`skills/aistudio-offload`](skills/aistudio-offload/SKILL.md) | Gemini в AI Studio |
| [`skills/mistral-offload`](skills/mistral-offload/SKILL.md) | Mistral Le Chat — **не используется** (решение владельца 04-11-2026: лимит ~20 сообщений, не стоит того) |
| [`skills/deepseek-offload`](skills/deepseek-offload/SKILL.md) | DeepSeek |
| [`skills/grok-offload`](skills/grok-offload/SKILL.md) | Grok в X |
| [`skills/qwen-offload`](skills/qwen-offload/SKILL.md) | Qwen Chat |
| [`skills/zai-offload`](skills/zai-offload/SKILL.md) | Z.ai (GLM) — **не используется**: показывает капчу (решение владельца 04-11-2026) |
| [`skills/arena-offload`](skills/arena-offload/SKILL.md) | Arena: одна выбранная модель; переписка может стать публичной, поэтому только для задач с публичными данными |
| [`skills/cerebras-offload`](skills/cerebras-offload/SKILL.md) | Cerebras (Qwen, GPT OSS) |
| [`skills/copilot-offload`](skills/copilot-offload/SKILL.md) | Microsoft Copilot — **не используется**: капча (решение владельца 04-11-2026). **пока не работает** (запрос не отправляется) |

Qwen, Z.ai, Arena и Cerebras проверены настоящим запросом 2026-11-03: роутер на Claude Haiku, тексты скиллов написала Gemini через `aistudio-offload`. Вывод из проверок: текст в поле ввода надо печатать (`computer` type), а не подставлять через `form_input`. Подстановка не даёт событий клавиатуры, и Z.ai и Copilot отвечают на неё капчей.

Каждый скилл — это `SKILL.md`, инструкция агенту. У каждого скилла есть `vendor/`: спецификация формата [ap](https://github.com/unxed/ap) (`ap.md`) и патчер (`ap.py`). Код модель возвращает только патчем `ap`, unified diff запрещён.

Правило: роутер не делает работу сам. Он только передаёт задачу модели и возвращает её ответ дословно.

Примеры задач: [`showcase/tasks`](showcase/tasks).
