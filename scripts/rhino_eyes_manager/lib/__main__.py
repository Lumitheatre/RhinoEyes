"""Entrypoint for RhinoEyes manifest manager CLI."""

import argparse
import sys
from pathlib import Path

from .manifest_manager import ManifestManager
from .sheet_builder import SheetBuilder
from .constants import VERSION


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="rhino_eyes_manager",
        description="Manage an eye animation manifest for character clips (Godot ConfigFile format).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s eye_manifest.cfg                          # Update existing manifest
  %(prog)s -u ./clips eye_manifest.cfg               # Generate/update from clips
  %(prog)s -u ./clips -d eye_manifest.cfg            # Generate/update from clips and delete missing files
  %(prog)s --migrate old_manifest.cfg                # Migrate old manifest format to new namespace format
  %(prog)s --allocate-clips-to-sheets eye_manifest.cfg  # Allocate clips to sheets based on capacity
  %(prog)s --reallocate-clips-to-sheets eye_manifest.cfg # Destructively reallocate all clips to sheets
        """,
    )

    parser.add_argument(
        "manifest_file",
        help="Path to manifest file to create or update",
    )

    parser.add_argument(
        "-u",
        "--update-from-clips",
        metavar="CLIP_DIR",
        help="Update manifest by scanning CLIP_DIR for character subdirectories with .mov clips. "
        "Filenames are the source of truth; physical files don't need to exist to work with the manifest. "
        "-d/--delete-absent only has effect when this flag is used.",
    )

    parser.add_argument(
        "-d",
        "--delete-absent",
        action="store_true",
        help="When used with -u/--update-from-clips: remove entries for files no longer present in clip directory. "
        "Has no effect without -u/--update-from-clips.",
    )

    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Migrate old manifest format (without namespace prefixes) to new namespace format. "
        "Required when loading manifests with version mismatch.",
    )

    parser.add_argument(
        "--allocate-clips-to-sheets",
        action="store_true",
        help="Allocate clips to sheets based on available capacity (grid dimensions). "
        "Sequentially assigns sheet_id to unassigned clips.",
    )

    parser.add_argument(
        "--reallocate-clips-to-sheets",
        action="store_true",
        help="Destructively clear all clip-to-sheet assignments and reallocate from scratch. "
        "All existing sheet_id values will be removed and reassigned.",
    )

    parser.add_argument(
        "--build-sheets",
        action="store_true",
        help="Build animation sheets from the manifest configuration. Requires manifest to have sheets defined.",
    )

    parser.add_argument(
        "--regenerate-tiles",
        action="store_true",
        help="When used with --build-sheets: recreate all tiles even if they already exist. Without this flag, existing tiles are skipped.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest_file)
    manager = ManifestManager()

    try:
        if args.migrate:
            # Migrate old manifest format
            import configparser

            manifest = configparser.ConfigParser()
            manifest.read(manifest_path)
            migrated_manifest = manager.migrate_old_manifest(manifest)
            manager.save_manifest(migrated_manifest, manifest_path)
            print(f"Migrated manifest: {manifest_path}")
            return

        if args.update_from_clips:
            # Update from clips directory
            is_new, result_path = manager.update_manifest_from_clips(
                args.update_from_clips, manifest_path, args.delete_absent
            )

            status = "Created new" if is_new else "Updated existing"
            print(f"{status} manifest: {result_path}")

            # Also apply normal update operations
            result_path = manager.update_manifest(manifest_path)
            print(f"Updated manifest: {result_path}")
            return

        if args.allocate_clips_to_sheets or args.reallocate_clips_to_sheets:
            # Allocate clips to sheets
            manifest = manager.load_manifest(manifest_path)
            if manifest is None:
                raise ValueError(f"Manifest file '{manifest_path}' does not exist.")

            manager.allocate_clips_to_sheets(
                manifest, clear_existing=args.reallocate_clips_to_sheets
            )
            manager.save_manifest(manifest, manifest_path)
            
            operation = "Reallocated" if args.reallocate_clips_to_sheets else "Allocated"
            print(f"{operation} clips to sheets: {manifest_path}")
            return

        if args.build_sheets:
            # Build sheets from manifest
            manifest = manager.load_manifest(manifest_path)
            if manifest is None:
                raise ValueError(f"Manifest file '{manifest_path}' does not exist.")
            
            builder = SheetBuilder(manifest, regenerate_tiles=args.regenerate_tiles)
            builder.run()
            print(f"Built sheets from manifest: {manifest_path}")
            return

        # Normal update operation
        result_path = manager.update_manifest(manifest_path)
        print(f"Updated manifest: {result_path}")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
