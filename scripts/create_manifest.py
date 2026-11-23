"""Create the versioned demo product manifest from the OpenText catalog.

Discovery tries the product listing, then the search API, then the product feed. A source that
answers HTTP 401/403, redirects to a login page, or returns login content is skipped and never
retried with credentials. Selection is deterministic for a given manifest version and seed.

The approved manifest is reused for normal runs. Replacing it needs an explicit new
`--manifest-version` and, if the output file exists, `--replace`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from product_support_agent.catalog import CatalogClient, create_manifest
from product_support_agent.config import Settings


def _parse_args(argv: list[str], settings: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(settings.manifest_path))
    parser.add_argument(
        "--manifest-version",
        required=True,
        help="new version label, for example opentext-2026-12-01-v2",
    )
    parser.add_argument("--seed", default=settings.manifest_seed)
    parser.add_argument("--max-products", type=int, default=settings.max_demo_products)
    parser.add_argument(
        "--replace", action="store_true", help="overwrite an existing manifest file"
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.output.exists() and not args.replace:
        print(f"{args.output} exists; pass --replace to select a new manifest", file=sys.stderr)
        return 2

    client = CatalogClient(
        listing_url=settings.catalog_listing_url,
        search_url=settings.catalog_search_url,
        feed_url=settings.catalog_feed_url,
        max_pages=settings.catalog_max_pages,
        timeout_seconds=settings.catalog_timeout_seconds,
        max_response_bytes=settings.catalog_max_response_bytes,
    )
    outcome = await client.discover()
    for note in outcome.notes:
        print(f"skipped: {note}")
    if not outcome.products:
        print(f"catalog is empty ({outcome.source}: {outcome.reason}); no manifest written")
        return 1

    manifest = create_manifest(
        outcome.products,
        manifest_version=args.manifest_version,
        seed=args.seed,
        selection_timestamp=datetime.now(UTC).isoformat(),
        max_products=args.max_products,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"catalog source: {outcome.source}; {len(outcome.products)} products; "
        f"selected {len(manifest.selected_products)}; wrote {args.output}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    args = _parse_args(sys.argv[1:] if argv is None else argv, settings)
    return asyncio.run(_run(args, settings))


if __name__ == "__main__":
    raise SystemExit(main())
