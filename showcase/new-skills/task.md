# Task: five new offload skills (instructions only) for unxed/AI

Repository root: ~/dev/AI. Existing skills are pure instruction files: `skills/<name>-offload/SKILL.md`. A router agent follows them to drive Claude's built-in browser.

The five new files ALREADY EXIST as exact copies of the attached template `skills/deepseek-offload/SKILL.md`:
`skills/qwen-offload/SKILL.md`, `skills/zai-offload/SKILL.md`, `skills/copilot-offload/SKILL.md`, `skills/arena-offload/SKILL.md`, `skills/cerebras-offload/SKILL.md`.

Change ONLY the site-specific parts in each copy, exactly as the existing skills differ from each other:
- the front matter `name` and `description`;
- the `#` title;
- the "Исполнитель" names in the intro and Terminology;
- step 1.2 (URL) and step 1.3 (login message);
- step 1.5 (model);
- the `vendor/ap.md` path (it must point to the skill's own `vendor/ap.md`);
- the drive-mode sentence about switching off the site's web search and tools;
- for Arena and Cerebras, add the extra rules below, as new bullets after step 1.5.

Keep everything else verbatim (Russian, like the template). The vendor rule must name the vendor correctly for each skill.

Answer with ONE small ap patch: for each of the five files, REPLACE / INSERT_AFTER directives with snippets copied verbatim from the template (the files are identical to it). Do NOT recreate whole files. Use a fresh random 8-hex patch ID, not the spec's example ID.

Facts collected from the live pages (2026-11-03, signed in):

1. `skills/qwen-offload/SKILL.md`: Qwen Chat by Alibaba, vendor `alibaba`.
   - New chat: https://chat.qwen.ai/
   - Input: textarea "How can I help you today?".
   - Model selector at the top shows "Qwen3.7-Plus" (default); a mode switch shows "Auto".
   - A cookie banner offers "Use necessary cookies only"; pick that.
   - Popups with "取消" (cancel) / "Continue" may appear; close them with "取消"/Close.
   - "Upgrade" buttons: never click.
   - Models: the default, or the one the caller names. Thinking/search only if the caller asks.
2. `skills/zai-offload/SKILL.md`: Z.ai Chat with GLM models by Zhipu, vendor `zhipu`.
   - New chat: https://chat.z.ai/ (button "New Chat").
   - Input: textarea "Send a Message".
   - Model button shows "GLM-5.3-Flash" (default).
   - Agent/mode buttons "Full-Stack", "Writing", "Data Insight", "PPT", "Web Site", "ZCode" must NOT be used: plain chat only.
   - "API" is not used.
3. `skills/copilot-offload/SKILL.md`: Microsoft Copilot, which runs OpenAI models, vendor `openai`.
   - New chat: https://copilot.microsoft.com/ (redirects to copilot.com/chat). The UI language may be Russian.
   - Input: "Сообщение для Copilot" / "Message Copilot".
   - Use the "Временный чат" / "Temporary chat" button so nothing stays in history.
   - The mode button shows "Auto"; keep it unless the caller asks for Think Deeper.
   - Never click "Купить"/"Buy" or "Повысьте статус"/"Upgrade".
4. `skills/arena-offload/SKILL.md`: Arena (formerly LMArena), multi-vendor.
   - New chat: https://arena.ai/chat
   - Input: a textarea. Model selection: the "Mention a model" button or typing "@" in the input. Mode button "Chat" (not "Agent", "Build a website", "Generate images" or "Search the Web"). Button "Modality: Auto".
   - Send: "Send message". Banners: "Dismiss banner" / "Hide this".
   - RULES specific to Arena:
     a) Always pick ONE specific model directly (never an anonymous battle). The vendor rule applies to the chosen model's vendor: it must differ from the router's vendor and from every vendor already in the chain. Name the chosen model in the report.
     b) Arena may publish conversations in public datasets. Never send private code or data unless the caller explicitly says it may be public. Otherwise refuse and report why.
5. `skills/cerebras-offload/SKILL.md`: Cerebras Inference chat, which serves open models, multi-vendor.
   - New chat: https://chat.cerebras.ai/chat
   - Input: textarea "What do you want to know?". The model button shows the current model, e.g. "Qwen 3.8 27B" (default).
   - Cookie banner: "Reject All".
   - Never use "GET FREE API KEY", "Coding agent"/"BUILD SOMETHING" (/code) or "Data applications" (/business).
   - Vendor rule: it applies to the chosen model's vendor (Qwen -> alibaba, GLM -> zhipu, Llama -> meta, gpt-oss -> openai, etc.). Name the chosen model in the report.
   - Answers are very fast, so polling can be every 3-5 s.

Paths in the patch are relative to the repository root.
