from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sync PII service OpenAPI contract into this repo.\n\n"
            "This script clones the PII service repo at a pinned ref, copies the OpenAPI file\n"
            "into contracts/pii/openapi.yaml, and updates contracts/pii/SYNCED_FROM.txt."
        )
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("PII_REPO_URL", ""),
        help="Git URL/path to the PII service repository (env: PII_REPO_URL).",
    )
    parser.add_argument(
        "--ref",
        default=os.environ.get("PII_REPO_REF", "main"),
        help="Git ref (tag/branch/commit) to sync from (env: PII_REPO_REF, default: main).",
    )
    parser.add_argument(
        "--openapi-path",
        default=os.environ.get("PII_OPENAPI_PATH", "openapi.yaml"),
        help="Path to OpenAPI file within the PII repo (env: PII_OPENAPI_PATH, default: openapi.yaml).",
    )
    args = parser.parse_args()

    if not args.repo:
        print("ERROR: --repo is required (or set env PII_REPO_URL).", file=sys.stderr)
        return 2

    workspace_root = Path(__file__).resolve().parents[1]
    out_openapi = workspace_root / "contracts" / "pii" / "openapi.yaml"
    out_synced = workspace_root / "contracts" / "pii" / "SYNCED_FROM.txt"

    out_openapi.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pii-openapi-sync-") as tmpdir:
        tmp = Path(tmpdir)
        repo_dir = tmp / "pii-repo"

        # Clone shallow by default; still supports tags/commits for most cases.
        run(["git", "clone", "--no-checkout", "--depth", "1", args.repo, str(repo_dir)])
        run(["git", "fetch", "--depth", "1", "origin", args.ref], cwd=repo_dir)
        run(["git", "checkout", args.ref], cwd=repo_dir)

        src_openapi = repo_dir / args.openapi_path
        if not src_openapi.exists():
            print(
                f"ERROR: OpenAPI file not found in repo at path: {args.openapi_path}",
                file=sys.stderr,
            )
            return 3

        shutil.copyfile(src_openapi, out_openapi)

        synced_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        out_synced.write_text(
            "\n".join(
                [
                    "This file is updated by scripts/sync_pii_openapi.py",
                    "",
                    f"pii_repo_url: {args.repo}",
                    f"pii_repo_ref: {args.ref}",
                    f"pii_openapi_path: {args.openapi_path}",
                    f"synced_at_utc: {synced_at}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    print(f"Synced OpenAPI to: {out_openapi}")
    print(f"Updated metadata: {out_synced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

