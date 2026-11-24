---
title: ADR-0009 Queue-Driven Ingestion
description: One queue message per product, processed one at a time, with a recorded outcome for every product
author: Udaybhanu Karmakar
ms.date: 2026-11-24
ms.topic: decision
keywords:
  - ADR
  - ingestion
  - queue
---

## Status

Accepted.

## Context

The brief asks for ingestion through a queue in which each item holds one
product, a worker that takes one item at a time, and a recorded success or
failure for every operation. It names Azurite locally and Azure Storage Queue
in the cloud.

## Decision

* `scripts/run_queue_ingestion.py` has four commands: `enqueue`, `work`, `run`
  (enqueue then work), and `status`.
* **Enqueue** starts a run and puts one message on the `product-ingestion` queue
  for each manifest product with an approved source. A message carries only the
  run ID, product ID, product name, and support-page URL. Products without a
  source are recorded straight away as `skipped` with the reason
  `no_public_source`.
* **Work** takes one message at a time with a 15-minute visibility timeout,
  runs the source worker ([ADR-0006](adr-0006-periodic-resumable-source-ingestion.md))
  for that product, records the outcome and page counts, and only then deletes
  the message.
* **Outcomes** are `success`, `partial`, `skipped` (no source, or protected
  content), `failed`, and `dead_letter`. The run is `completed` when every
  product has an outcome, or `completed_with_errors` if any is partial, failed,
  or dead-lettered.
* **Poison messages.** A message delivered five times
  (`PRODUCT_SUPPORT_POISON_DEQUEUE_COUNT`) is recorded as `dead_letter` and moved
  to `product-ingestion-poison`.
* **Budget.** If the run's request budget is spent, the current product is
  requeued with a one-hour delay and a fresh delivery count, and the worker
  stops.
* **One worker at a time.** The worker takes the same lease as the scheduled
  script, so the request budget and per-host spacing hold.
* **Status** is available from the command and from `GET /ingestion/runs/latest`
  and `GET /ingestion/runs/{run_id}`.
* **Authentication.** Locally, a connection string to Azurite. In Azure, the
  storage account URL and the job's managed identity; shared keys are disabled
  on the account.

## Rationale

Recording before deleting makes delivery at-least-once without losing an
outcome, and the source worker's fetch state and content hashes make a repeated
product cheap and harmless. A failing product cannot stall the others.

## Alternatives considered

* A single loop over all products: simpler, but one failure can stop a run, and
  per-product outcomes are not durable.
* Several workers in parallel: rejected for now, because the request budget and
  host spacing are enforced per process.

## Consequences

* Ingestion is sequential. Parallel workers need a shared rate limiter per
  source host.
* A stopped run leaves its lease for up to 6 hours; see the
  [support guide](../support-ownership.md) for how to clear it.
