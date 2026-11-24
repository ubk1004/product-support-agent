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
Azure AI Search services, and real traces from the Aspire dashboard. It is
recorded at 1920x1080 and 100% zoom so the whole width of the page is visible.
It shows questions, answers, and trace timings only, and no credentials or
settings.

A native drop-down list is drawn by the operating system, not the page, so it
never appears in a browser recording. To show the product filter's values, the
recorder expands the real `<select>` in place, highlights the option being
chosen, and then selects it.

## Record

1. Start the stack and wait until it is healthy:

   ```powershell
   podman compose up --build -d
   ```

2. Install the recorder, install Playwright's Chromium once, and record. The
   documentation must already be ingested (see the
   [local development guide](../../docs/operations/local-development.md)):

   ```powershell
   cd scripts/demo
   npm install
   npx playwright install chromium
   npm run record
   ```

The run takes a few minutes because it waits for each live answer. Set
`DEMO_BASE_URL` (default `http://127.0.0.1:3000`) to record another web app and
`DEMO_DASHBOARD_URL` (default `http://127.0.0.1:18888`) to capture another
telemetry dashboard.

Answers come from a language model, so wording differs between recordings.
Review the new video before committing it. If an answer is wrong or a step
fails, record again.
