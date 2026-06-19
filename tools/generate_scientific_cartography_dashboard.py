#!/usr/bin/env python3
"""CLI for generating static HTML dashboard from Scientific Cartography artifacts.

Usage:
    python3 tools/generate_scientific_cartography_dashboard.py \\
      --artifact-dir artifacts/scientific_cartography/2026-06-10 \\
      --output-dir /tmp/sc_lg4a_dashboard

This generates static HTML pages only. No server, no runtime dependencies.
"""

import argparse
import json
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scientific_cartography.dashboard_static.generator import DashboardGenerator


def main():
    parser = argparse.ArgumentParser(
        description="Generate static HTML dashboard from Scientific Cartography artifacts"
    )
    parser.add_argument(
        "--artifact-dir",
        required=True,
        help="Path to Scientific Cartography artifact directory",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for generated HTML files",
    )

    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    output_dir = Path(args.output_dir)

    # Validate artifact dir exists
    if not artifact_dir.exists():
        print(f"ERROR: Artifact directory not found: {artifact_dir}", file=sys.stderr)
        return 1

    print(f"Generating dashboard from: {artifact_dir}")
    print(f"Output directory: {output_dir}")
    print()

    try:
        generator = DashboardGenerator(str(artifact_dir), str(output_dir))
        manifest = generator.generate()

        print(f"✓ Dashboard generated successfully")
        print()
        print("Generated files:")
        for page in manifest["pages_written"]:
            print(f"  - {page}.html")
        print(f"  - dashboard_manifest.json")
        print()
        print(f"Artifacts read: {len(manifest['artifacts_read'])}")
        print(f"Artifacts missing: {len(manifest['artifacts_missing'])}")
        if manifest["artifacts_missing"]:
            print(f"  Missing: {', '.join(manifest['artifacts_missing'])}")
        print()
        print(f"Governance status:")
        for flag, value in manifest["governance_flags"].items():
            status = "✓" if value is True or value is False else "?"
            print(f"  {status} {flag}: {value}")
        print()
        print(f"Output: {output_dir}")
        print(f"Open in browser: file://{output_dir}/index.html")

        return 0

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
