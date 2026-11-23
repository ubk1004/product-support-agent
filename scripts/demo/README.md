---
title: Demo recorder
description: Regenerate the demo walkthrough video from the running local stack
author: Udaybhanu Karmakar
ms.date: 2026-11-23
ms.topic: how-to
---

`record-demo.mjs` drives the running web app with Playwright and writes:

* `docs/demo/product-support-agent-demo.webm`, the walkthrough linked from the
  [README](../../README.md).
* `docs/demo/poster.png`, the still image shown in the README.

The video uses the real stack: real answers from the configured Foundry and
Azure AI Search services. It shows questions and answers only, and no
credentials or settings.

## Record

1. Start the stack and wait until it is healthy:

   ```powershell
   podman compose up --build -d
   ```

2. Install the recorder and record. Playwright's Chromium must be installed
   (`npx playwright install chromium` once):

   ```powershell
   cd scripts/demo
   npm install
   npm run record
   ```

The run takes a few minutes because it waits for each live answer. Set
`DEMO_BASE_URL` to record against another address.

Answers come from a language model, so wording differs between recordings.
Review the new video before committing it. If an answer is wrong or a step
fails, record again.
