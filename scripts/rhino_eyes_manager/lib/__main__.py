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
  %(prog)s manage eye_manifest.cfg                                         # Update existing manifest
  %(prog)s manage -u ./clips eye_manifest.cfg                              # Generate/update from clips
  %(prog)s manage -u ./clips -d eye_manifest.cfg                           # Generate/update from clips and delete missing
  %(prog)s manage --reallocate-clips-to-sheets eye_manifest.cfg            # Reallocate clips to sheets
  %(prog)s manage --regenerate-loop-offset eye_manifest.cfg                # Regenerate loop offsets
  %(prog)s init new_manifest.cfg                                           # Create a blank manifest
  %(prog)s init -u ./clips new_manifest.cfg                                # Create manifest from clips
  %(prog)s migrate old_manifest.cfg                                        # Migrate old manifest format
  %(prog)s build-sheets eye_manifest.cfg                                   # Build sheets from manifest
  %(prog)s build-sheets --regenerate-tiles eye_manifest.cfg                # Build sheets, regenerating tiles
  %(prog)s build-sheets --regenerate-channel-grids eye_manifest.cfg        # Build sheets, regenerating channel grids
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
        "--regenerate-loop-offset",
        action="store_true",
        help="Regenerate loop_offset values for all clips with new random values between 0 and 1.",
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
        action="store_true",
        help="Recreate all tiles even if they already exist. Without this flag, existing tiles are skipped.",
    )
    build_sheets_parser.add_argument(
        "--regenerate-channel-grids",
        action="store_true",
        help="Regenerate intermediate channel grid files (R, G, B) even if they exist. Useful for changing encoding parameters.",
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

    # Regenerate loop offsets if requested
    if args.regenerate_loop_offset:
        print("Regenerating loop_offset values...")
        manager.regenerate_loop_offsets(manifest)

    # Update and save manifest
    result_path = manager.update_manifest(manifest_path, manifest=manifest)
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

    # Build sheets from manifest
    builder = SheetBuilder(
        manifest, 
        regenerate_tiles=args.regenerate_tiles,
        regenerate_channel_grids=args.regenerate_channel_grids
    )
    builder.run()
    print(f"Built sheets from manifest: {manifest_path}")


if __name__ == "__main__":
    main()
