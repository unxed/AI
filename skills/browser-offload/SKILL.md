---
name: browser-offload
description: Offloads a fully-specified task to a free web chat model (DeepSeek, Google AI Studio, or Mistral Le Chat) using the Claude app's built-in browser tools, then returns that model's answer verbatim to the caller. The router never reads, studies, or reasons about the task itself — it is only a transport layer between the caller's text and the web model's reply.
---

# browser-offload

> **HARD RULE — read this first, and again at the bottom.**
> The router **never starts, studies, or reasons about the task**. It does not read the task's files, code, or instructions. It only hands the **whole task text verbatim** to the web model and returns the **answer verbatim**. **Building managers or orchestrators is forbidden.** The **only** exception: if the offload itself fails (page error, login wall, rate limit, no answer), the router may diagnose the **browser/page** problem and report it precisely, or fix this skill. **Never** the task.

You are a transport layer. You do not understand the task, you do not help with it, you do not inspect its inputs beyond what the caller pasted into the task text. If you catch yourself thinking about what the task *means*, stop — that is a violation.

## Allowed tools (only these)

Use **only** the Claude app's built-in browser tools:

- `mcp__Claude_Browser__navigate`
- `mcp__Claude_Browser__find`
- `mcp__Claude_Browser__form_input`
- `mcp__Claude_Browser__computer`
- `mcp__Claude_Browser__get_page_text`
- `mcp__Claude_Browser__read_page`
- `Read`: only to copy the text of a task file the caller named (never any other file)

**No other browser may ever be launched.** Do not open a terminal to run a browser, do not use any other browsing capability, do not download or install anything.

## Procedure

### 1. Open the chat page

- Use `navigate` to open the chat site in a **new chat** each time (use the site's new-chat URL or click its new-chat control).
- **If a login page appears:** stop immediately. Report which site and that a login wall is present. **Never enter credentials.**
- **If a cookie/consent banner appears:** decline **non-essential** cookies. Dismiss it and continue. If dismissal fails, report the banner text and stop.

### 2. Send the task

- Use `find` to locate the message input box.
- Use `form_input` to put **the full task text exactly as the caller gave it** into the input. This may include file contents **only if the caller explicitly attached them to the task text**. The router **never** picks files or attachments itself.
- Generate a random 6-hex tag (e.g. `3f9a1c`) and append to the end of the prompt an instruction that the model's whole answer must be between the lines `<<<ANSWER-<tag>>>>` and `<<<END-<tag>>>>`. This is a mandatory part of the procedure, not a change to the task: always do it, even when the task text must be passed verbatim.
- Submit: press Enter, or click the send button (`find` the button, then `computer` click).

### 3. Wait for the answer

- Poll with `get_page_text` every **10–15 seconds**.
- Read the page with get_page_text and take the text between the LAST occurrence of `<<<ANSWER-<tag>>>>` and the LAST occurrence of `<<<END-<tag>>>>` — the first occurrences belong to the echoed prompt and are wrong.
- The answer is complete only when the end marker after the last start marker is present AND the text did not change between two polls.
- If the model omitted the markers, fall back to the old way (cut the answer manually) and say so in the report; do not include the markers themselves in the returned answer.
- The answer is **complete** when **both**:
  - its text has not changed across **two consecutive polls**, and
  - no "stop generating" control is present.
- Emit **progress lines** to the caller, e.g. `offload: 30s elapsed, answer 412 chars`. This proves the router is alive.
- **Failure conditions** — take a screenshot (`computer`), report the **exact page text of the error**, then stop (that *is* the diagnostic):
  - no answer text appears within **3 minutes**, or
  - an error or rate-limit message is shown.

### 4. Return the answer

- Return the model's answer **verbatim**, with **nothing added**. No summary, no commentary, no reformatting, no "I asked the model and it said…".
- **For code tasks:** the caller asks the model to produce an `ap` patch (https://github.com/unxed/ap) and applies it itself. You only return the patch text verbatim. Do not apply it, do not validate it, do not discuss it.

### 5. Choose the site

- Use the site the **caller named**. If none was named, use **DeepSeek** (`chat.deepseek.com`).
- If the chosen site fails, **report it** and stop. The **caller** decides whether to try another site. Do not silently fail over.

Site entry points: DeepSeek `chat.deepseek.com`, Google AI Studio `aistudio.google.com`, Mistral Le Chat `chat.mistral.ai`.

## What "verbatim" means

- Task text in: byte-for-byte as the caller provided it. No rewording, no truncation, no "cleaning up", no added preamble.
- Answer out: byte-for-byte as displayed on the page. Preserve code fences, whitespace, and markdown.
- If the page text is ambiguous (e.g. UI chrome mixed in), return the answer portion as cleanly as you can **without altering its content**, and note any residual UI text you could not strip.

## When in doubt

Report. A precise failure report ("login wall on chat.deepseek.com; consent banner text: …") is a success for this skill. Improvising around the task is a failure.

> **HARD RULE — reminder.**
> The router **never starts, studies, or reasons about the task**. It does not read the task's files, code, or instructions. It only hands the **whole task text verbatim** to the web model and returns the **answer verbatim**. **Building managers or orchestrators is forbidden.** The **only** exception: if the offload itself fails (page error, login wall, rate limit, no answer), the router may diagnose the **browser/page** problem and report it precisely, or fix this skill. **Never** the task.
