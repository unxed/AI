# AI: скиллы оффлоадинга

Скиллы для агента. Дешёвый роутер передаёт задачу модели через её веб-чат. Вся работа с моделью идёт во встроенном браузере Claude (`mcp__Claude_Browser__*`), в собственной вкладке агента. Консольных клиентов нет.

| Скилл | Модель |
|---|---|
| [`skills/browser-offload`](skills/browser-offload/SKILL.md) | DeepSeek, AI Studio или Mistral по выбору вызывающего |
| [`skills/aistudio-offload`](skills/aistudio-offload/SKILL.md) | Gemini в AI Studio |
| [`skills/mistral-offload`](skills/mistral-offload/SKILL.md) | Mistral Le Chat |
| [`skills/deepseek-offload`](skills/deepseek-offload/SKILL.md) | DeepSeek |
| [`skills/grok-offload`](skills/grok-offload/SKILL.md) | Grok в X |

Каждый скилл — это `SKILL.md`, инструкция агенту. У четырёх скиллов, кроме `browser-offload`, есть `vendor/`: спецификация формата [ap](https://github.com/unxed/ap) (`ap.md`) и патчер (`ap.py`). Код модель возвращает только патчем `ap`, unified diff запрещён.

Правило: роутер не делает работу сам. Он только передаёт задачу модели и возвращает её ответ дословно.

Примеры задач: [`showcase/tasks`](showcase/tasks).
