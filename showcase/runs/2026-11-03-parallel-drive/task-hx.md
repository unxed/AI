Ты — Лунобот (бот номер 2). Инструкция LUNOBOT.md приложена файлом, следуй ей. Также приложены: hx-far-run.yml (workflow стенда из unxed/sandbox) и UTF8-DOS.md (план из unxed/go2dos, см. §7). Рабочий каталог /home/unxed/.config/Claude/scratch-workspaces/aea67e26-ea4e-4e2c-b2f0-286197003349/8deeedee-b694-4fca-8ead-f7d695add1cb/scratch-2026-10-31-632f6c/offload/hxwork. В нём клоны unxed/lunobot (там tools/claims.py), unxed/go2dos и unxed/sandbox. Другие нужные файлы запрашивай целиком действием attach (raw URL), run используй для grep, gh и коротких команд.

Задача — ОДИН небольшой шаг по тикету unxed/go2dos#70 «Unicode Far Manager под HX в DOSBox-X: UTF-8 имена и буфер обмена». Прочитай тикет и комментарии через `gh issue view 70 -R unxed/go2dos --comments`, читай частями через `| tail -c` или `| head`.

Известные факты, перепроверять их не нужно:
- Far 3 x86 на стенде останавливался в sqlite3.dll на SSE2 (66 0F 13, MOVLPD), потому что в DOSBox-X 2024.03.01 из apt SSE2 нет.
- Поддержку SSE2 владелец вмержил в DOSBox-X: PR joncampbell123/dosbox-x#6716 «CPU: SSE2 (opt-in "enable sse2"), and optionally cputype=pentium_4», влит 24.10.2026. Последний релиз DOSBox-X (2026.10.01) вышел раньше и SSE2 не содержит. Значит, нужна сборка из master. Точные имена параметров конфига смотри в описании PR через `gh pr view 6716 -R joncampbell123/dosbox-x`.

Шаг:
1. В unxed/sandbox научить стенд hx-far-run.yml запускать Far 3 x86 на DOSBox-X, собранном из master joncampbell123/dosbox-x (коммит не раньше слияния #6716), с включённым SSE2. Сделать это опцией workflow, не ломая текущий режим. Собирать в CI, кэш по желанию.
2. Запустить workflow в CI (`gh workflow run`, затем следить через `gh run watch` или `gh run view`) и выяснить, где Far 3 останавливается теперь: следующая отсутствующая функция или DLL, другая инструкция — или Far дошёл до панелей. Локальная сборка доказательством не считается, только CI.
3. Отчитаться комментарием в unxed/go2dos#70, как требует LUNOBOT.md (захват и отчёт через его инструменты): что изменено, ссылка на run, что видно на скриншотах и в логе, какой следующий шаг.

Не делай больше этого шага: H2–H7 из тикета не трогай. Ветки владельца (dkrnl32-cp-utf8 в unxed/HX и другие чужие ветки) не трогай. Дедлайн 60 минут. Подпись: роутер Claude Haiku, воркер DeepSeek. Когда закончишь — действие done с кратким итогом и ссылками на коммит, run и комментарий.
