"""Entrypoint for RhinoEyes manifest manager CLI."""

import argparse
import sys
from pathlib import Path
from typing import Set

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
  %(prog)s manage eye_manifest.cfg                                    # Update existing manifest
  %(prog)s manage -u ./clips eye_manifest.cfg                         # Generate/update from clips
  %(prog)s manage -u ./clips -d eye_manifest.cfg                      # Generate/update from clips and delete missing
  %(prog)s manage --reallocate-clips-to-sheets eye_manifest.cfg       # Reallocate clips to sheets
  %(prog)s init new_manifest.cfg                                      # Create a blank manifest
  %(prog)s init -u ./clips new_manifest.cfg                           # Create manifest from clips
  %(prog)s migrate old_manifest.cfg                                   # Migrate old manifest format
  %(prog)s build-sheets eye_manifest.cfg                              # Build sheets from manifest (mtime-based incremental)
  %(prog)s build-sheets --ignore-changed-tiles eye_manifest.cfg        # Incremental by existence only (no mtime checks)
  %(prog)s build-sheets --regenerate-tiles blink_a.mov,blink_b.mov eye_manifest.cfg  # Force specific tiles, then rebuild affected sheets
  %(prog)s build-sheets --regenerate-all eye_manifest.cfg              # Force regenerate all tiles and all sheets
  %(prog)s build-sheets --parallel-sheet-encoding eye_manifest.cfg     # Encode multiple sheets in parallel
        """,
    )

    # Add global flags (before subparsers)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    # Create subparsers for commands
    subparsers = parser.add_subparsers(
        dest="command",
        help="Command to execute",
    )

    # === MANAGE command ===
    manage_parser = subparsers.add_parser(
        "manage",
        help="Update an existing manifest (default behavior): allocate clips to sheets, update missing fields",
    )
    manage_parser.add_argument(
        "manifest_file",
        help="Path to manifest file to update",
    )
    manage_parser.add_argument(
        "-u",
        "--update-from-clips",
        metavar="CLIP_DIR",
        help="Update manifest by scanning CLIP_DIR for character subdirectories with .mov clips. "
        "Filenames are the source of truth; physical files don't need to exist.",
    )
    manage_parser.add_argument(
        "-d",
        "--delete-absent",
        action="store_true",
        help="When used with -u/--update-from-clips: remove entries for files no longer present in clip directory.",
    )
    manage_parser.add_argument(
    	"-r",
        "--reallocate-clips-to-sheets",
        action="store_true",
        help="Destructively clear all clip-to-sheet assignments and reallocate from scratch.",
    )
    manage_parser.add_argument(
        "--regenerate-clip-loop-offsets",
        action="store_true",
        help="Regenerate loop_offset values for all clips to randomize their loop phase.",
    )

    # === INIT command ===
    init_parser = subparsers.add_parser(
        "init",
        help="Create a blank new manifest with no entries",
    )
    init_parser.add_argument(
        "manifest_file",
        help="Path to new manifest file to create",
    )
    init_parser.add_argument(
        "-u",
        "--update-from-clips",
        metavar="CLIP_DIR",
        help="Populate new manifest by scanning CLIP_DIR for character subdirectories with .mov clips.",
    )
    init_parser.add_argument(
        "-d",
        "--delete-absent",
        action="store_true",
        help="When used with -u/--update-from-clips: remove entries for files no longer present in clip directory.",
    )

    # === MIGRATE command ===
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate old manifest format (without namespace prefixes) to new namespace format",
    )
    migrate_parser.add_argument(
        "manifest_file",
        help="Path to old manifest file to migrate",
    )

    # === BUILD-SHEETS command ===
    build_sheets_parser = subparsers.add_parser(
        "build-sheets",
        help="Build animation sheets from the manifest configuration",
    )
    build_sheets_parser.add_argument(
        "manifest_file",
        help="Path to manifest file to build sheets from",
    )
    build_sheets_parser.add_argument(
        "--regenerate-tiles",
        metavar="FILENAMES",
        help=(
            "Comma-separated list of *source* clip filenames to renormalize into tiles "
            "(e.g. blink_a.mov,blink_b.mov). Only those tiles (and the sheets that depend on them) "
            "will be regenerated."
        ),
    )
    build_sheets_parser.add_argument(
        "--ignore-changed-tiles",
        action="store_true",
        help=(
            "Disable modified-time dependency checks and only regenerate missing tiles/sheets (plus any explicitly forced via --regenerate-tiles/--regenerate-all)."
        ),
    )
    build_sheets_parser.add_argument(
        "--regenerate-all",
        action="store_true",
        help="Force regeneration of all tiles and all sheets (bulk rebuild).",
    )
    build_sheets_parser.add_argument(
        "--parallel-sheet-encoding",
        action="store_true",
        help="Encode sheets in parallel instead of sequentially. Uses more CPU/RAM.",
    )

    args = parser.parse_args()

    # If no command specified, default to 'manage'
    if args.command is None:
        # Shift arguments to treat first positional as manifest_file
        # This provides backward compatibility
        if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            args.command = "manage"
            args.manifest_file = sys.argv[1]
            # Re-parse with manage as the command
            args = parser.parse_args(["manage"] + sys.argv[1:])
        else:
            parser.print_help()
            sys.exit(1)

    manifest_path = Path(args.manifest_file)
    manager = ManifestManager()

    try:
        if args.command == "migrate":
            _handle_migrate(manager, manifest_path)

        elif args.command == "init":
            _handle_init(manager, manifest_path, args)

        elif args.command == "manage":
            _handle_manage(manager, manifest_path, args)

        elif args.command == "build-sheets":
            _handle_build_sheets(manager, manifest_path, args)

        else:
            parser.print_help()
            sys.exit(1)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _handle_migrate(manager, manifest_path):
    """Handle the migrate command."""
    import configparser

    manifest = configparser.ConfigParser()
    manifest.read(manifest_path)
    migrated_manifest = manager.migrate_old_manifest(manifest)
    manager.save_manifest(migrated_manifest, manifest_path)
    print(f"Migrated manifest: {manifest_path}")


def _handle_init(manager, manifest_path, args):
    """Handle the init command."""
    # Create new manifest
    manifest = manager.create_manifest()
    print("Created new manifest")

    # Update from clips if requested
    if args.update_from_clips:
        manager.update_manifest_from_clips(
            args.update_from_clips, manifest, args.delete_absent
        )
        print(f"Updated manifest from clips: {args.update_from_clips}")

    # Apply allocation (default behavior)
    manager.allocate_clips_to_sheets(manifest, clear_existing=False)
    print("Allocated clips to sheets")

    # Save manifest
    result_path = manager.update_manifest(manifest_path, manifest=manifest)
    print(f"Saved manifest: {result_path}")


def _handle_manage(manager, manifest_path, args):
    """Handle the manage command."""
    manifest = manager.load_manifest(manifest_path)

    if manifest is None:
        # Manifest doesn't exist
        if not args.update_from_clips:
            raise ValueError(
                f"Manifest file '{manifest_path}' does not exist. "
                f"Use -u/--update-from-clips to generate a new manifest from clips."
            )
        # Create new manifest
        manifest = manager.create_manifest()
        print("Created new manifest")
    else:
        print("Loaded existing manifest")

    # Update from clips if requested
    if args.update_from_clips:
        manager.update_manifest_from_clips(
            args.update_from_clips, manifest, args.delete_absent
        )
        print(f"Updated manifest from clips: {args.update_from_clips}")

    # Apply allocation
    manager.allocate_clips_to_sheets(
        manifest, clear_existing=args.reallocate_clips_to_sheets
    )
    operation = "Reallocated" if args.reallocate_clips_to_sheets else "Allocated"
    print(f"{operation} clips to sheets")

    # Update and save manifest
    result_path = manager.update_manifest(manifest_path, manifest=manifest, regenerate_loop_offsets=args.regenerate_clip_loop_offsets)
    print(f"Updated manifest: {result_path}")


def _handle_build_sheets(manager, manifest_path, args):
    """Handle the build-sheets command."""
    manifest = manager.load_manifest(manifest_path)

    if manifest is None:
        raise ValueError(
            f"Manifest file '{manifest_path}' does not exist. "
            "Cannot build sheets without a manifest."
        )

    print("Loaded manifest")

    def _parse_csv_filenames(value: str) -> Set[str]:
        parts = [p.strip() for p in value.split(",")]
        return {p.lower() for p in parts if p}

    regenerate_tile_names = None
    if args.regenerate_tiles:
        regenerate_tile_names = _parse_csv_filenames(args.regenerate_tiles)
        if not regenerate_tile_names:
            raise ValueError("--regenerate-tiles was provided but no filenames were parsed")

    # Build sheets from manifest
    builder = SheetBuilder(
        manifest,
        regenerate_tiles=regenerate_tile_names,
        ignore_changed_tiles=args.ignore_changed_tiles,
        regenerate_all=args.regenerate_all,
        sequential=not args.parallel_sheet_encoding,
    )
    builder.run()
    print(f"Built sheets from manifest: {manifest_path}")


if __name__ == "__main__":
    main()
