"""``aeread seal-manifest``: write or rebuild a bundle's kernel-standard manifest.

Two modes. ``--rebuild`` (the default when ``publication_manifest.json``
exists) re-seals the manifest in the kernel layout from the files on disk,
carrying every provenance field over and refusing any file whose bytes
differ from the digest the old manifest recorded. ``--new`` writes a fresh
manifest for a bundle that has none; it needs ``--publication-id`` and the
privacy boundary (``--included``, ``--excluded``).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .publication import (
    MANIFEST_FILENAME,
    rebuild_publication_manifest,
    seal_publication_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread seal-manifest",
        description="write or rebuild a bundle's kernel-standard publication manifest",
    )
    parser.add_argument("bundle", type=Path, help="evidence/<campaign_id> bundle root")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rebuild", action="store_true", help="re-seal the existing manifest from the files (default)")
    mode.add_argument("--new", action="store_true", help="write a fresh manifest for a bundle without one")
    parser.add_argument("--publication-id", help="--new: publication identity (defaults to the bundle directory name)")
    parser.add_argument("--campaign-id", help="--new: campaign identity, if the bundle publishes one campaign")
    parser.add_argument("--included", help="privacy boundary, what the bundle includes (required with --new; with --rebuild, supplies a missing boundary)")
    parser.add_argument("--excluded", help="privacy boundary, what the bundle excludes")
    parser.add_argument(
        "--source-bindings",
        help="--new: JSON object recording what the bundle was produced from",
    )
    args = parser.parse_args(argv)

    try:
        if args.new:
            if not (args.included and args.excluded):
                parser.error("--new requires --included and --excluded")
            manifest = seal_publication_manifest(
                args.bundle,
                publication_id=args.publication_id or args.bundle.name,
                campaign_id=args.campaign_id,
                privacy_boundary={"included": args.included, "excluded": args.excluded},
                source_bindings=json.loads(args.source_bindings) if args.source_bindings else None,
            )
        else:
            if not (args.bundle / MANIFEST_FILENAME).exists():
                parser.error(f"no {MANIFEST_FILENAME} to rebuild; use --new")
            if bool(args.included) != bool(args.excluded):
                parser.error("--included and --excluded go together")
            boundary = (
                {"included": args.included, "excluded": args.excluded} if args.included else None
            )
            manifest = rebuild_publication_manifest(args.bundle, privacy_boundary=boundary)
    except ValueError as error:
        parser.exit(1, f"aeread seal-manifest: {error}\n")
    print(
        f"{len(manifest['artifacts'])} artifacts sealed in {args.bundle / MANIFEST_FILENAME}; "
        f"manifest_sha256={manifest['manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
