#!/usr/bin/env python3

import argparse
import configparser
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

VERSION = "0.1.2"

def get_clips_for_character(char_dir: Path) -> List[str]:
    """Get sorted list of clips in character directory."""
    clips = sorted([f.name for f in char_dir.glob("*.mov")])
    return clips

def load_manifest(manifest_path: Path) -> Optional[Dict[str, Any]]:
    """Load existing manifest, return None if doesn't exist."""
    if not manifest_path.exists():
        return None
    
    config = configparser.ConfigParser()
    config.read(manifest_path)

    if ("DEFAULT" not in config or config["DEFAULT"].get("manifest_version") != VERSION):
        raise ValueError(f"Manifest file '{manifest_path}' is missing or has incompatible version. Expected version: {VERSION}")
    
    manifest = {}
    
    # Parse each section (actor/character)
    for actor in config.sections():
        if config.has_option(actor, "clips"):
            clips_str = config.get(actor, "clips")
            try:
                # Parse the JSON array string
                clips_list = json.loads(clips_str)
                manifest[actor] = clips_list
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in clips for actor '{actor}': {e}")
    
    return manifest if manifest else None

def save_manifest(manifest: Dict[str, Any], manifest_path: Path) -> None:
    """Save manifest to ConfigFile (.cfg) format."""
    config = configparser.ConfigParser()
    
    config.set('DEFAULT', 'manifest_version', VERSION)
    
    # Create a section for each actor
    for actor in sorted(manifest.keys()):
        config.add_section(actor)
        
        # Serialize clips as a JSON array string
        clips_json = json.dumps(manifest[actor], indent=2, separators=(', ', ': '))
        config.set(actor, "clips", clips_json)
    
    with open(manifest_path, 'w') as f:
        config.write(f)

def create_entry(path: str) -> Dict[str, Any]:
    """
    Create a new entry with minimal required fields.
    Only the path is populated; other fields are left for management.
    
    Args:
        path: Path to the clip file
    
    Returns:
        A new entry dict with just the path
    """
    return {"path": path}

def get_max_uid(manifest: Dict[str, Any]) -> int:
    """Get the maximum UID currently in the manifest, or -1 if none exist."""
    max_uid = 0
    for character_clips in manifest.values():
        for clip in character_clips:
            if "uid" in clip:
                max_uid = max(max_uid, clip["uid"])
    return max_uid

def assign_uids(manifest: Dict[str, Any]) -> None:
    """
    Assign UIDs to all entries that don't have one.
    Uses the maximum existing UID and increments from there.
    
    Modifies manifest in place.
    """
    next_uid = get_max_uid(manifest) + 1
    
    for character_clips in manifest.values():
        for entry in character_clips:
            if "uid" not in entry:
                entry["uid"] = next_uid
                next_uid += 1

def initialize_entry_fields(manifest: Dict[str, Any]) -> None:
    """
    Initialize missing fields in entries with default values.
    Ensures all entries have a consistent structure.
    
    Modifies manifest in place.
    """
    for character_clips in manifest.values():
        for entry in character_clips:
            entry.setdefault("enabled", "true")
            entry.setdefault("angle", 0)
            entry.setdefault("aggravation", 0)

def sort_entries(manifest: Dict[str, Any]) -> None:
    """
    Sort all entries by aggravation, then angle, then path.
    
    Modifies manifest in place.
    """
    for character_clips in manifest.values():
        character_clips.sort(key=lambda x: (x.get("aggravation", 0), x.get("angle", 0), x.get("path", "")))

def sync_manifest_from_clips(clip_dir: str, manifest: Dict[str, Any], delete_absent: bool = False) -> None:
    """
    Synchronize manifest with clips found in clip_dir.
    
    This function:
    - Creates new entries for clips not in manifest (just path field)
    - Removes entries for clips that no longer exist (if delete_absent=True)
    - Does NOT modify any other entry fields
    
    Modifies manifest in place.
    
    Args:
        clip_dir: Directory containing character subdirectories with .mov clips
        manifest: The manifest dict to synchronize
        delete_absent: If True, remove entries for files not found on disk
    """
    clip_dir_path = Path(clip_dir)
    
    # If delete_absent flag is set, remove entries for files not found on disk
    if delete_absent:
        print("Removing entries for files no longer present in clip directory...")
        for char_name in list(manifest.keys()):
            manifest[char_name] = [
                entry for entry in manifest[char_name]
                if Path(entry.get("path", "")).exists()
            ]
            # Remove character entirely if no entries remain
            if not manifest[char_name]:
                del manifest[char_name]
    
    # Process each character directory
    for char_dir in sorted(clip_dir_path.iterdir()):
        if not char_dir.is_dir():
            continue
        
        char_name = char_dir.name
        clips = get_clips_for_character(char_dir)
        
        if not clips:
            continue
        
        # Initialize character in manifest if not present
        if char_name not in manifest:
            manifest[char_name] = []
        
        existing_entries = manifest[char_name]
        new_entries = []
        
        # Process each clip file
        for clip_name in clips:
            file_path = f"{char_dir}/{clip_name}"
            
            # Check if this file already exists in manifest
            existing_entry = None
            for entry in existing_entries:
                if entry.get("path") == file_path:
                    existing_entry = entry
                    break
            
            if existing_entry:
                # Preserve existing entry
                new_entries.append(existing_entry)
            else:
                # Create new entry (just path, other fields added during management)
                new_entries.append(create_entry(file_path))
        
        if not delete_absent:
            # Add back any existing entries that reference missing files
            for entry in existing_entries:
                entry_path = entry.get("path", "")
                # Check if this entry is not in the new list
                if not any(e.get("path") == entry_path for e in new_entries):
                    new_entries.append(entry)
        
        manifest[char_name] = new_entries

def update_manifest_from_clips(clip_dir: str, manifest_path: Path, delete_absent: bool = False) -> Tuple[bool, str]:
    """
    Update manifest based on clips in directory.
    
    Scans clip_dir for character subdirectories and .mov files, syncs the manifest,
    then applies management updates.
    
    Args:
        clip_dir: Directory containing character subdirectories with .mov clips
        manifest_path: Output manifest file path
        delete_absent: If True, remove entries for files that no longer exist in clip_dir
    
    Returns:
        Tuple of (is_new: bool, manifest_path: str)
    """
    # Load or create manifest
    existing_manifest = load_manifest(manifest_path)
    is_new = existing_manifest is None
    manifest = existing_manifest if existing_manifest else {}
    
    # Sync with clips directory
    sync_manifest_from_clips(clip_dir, manifest, delete_absent)
    
    return is_new, str(manifest_path.resolve())

def update_manifest(manifest_path: Path, manifest_to_update: Optional[Dict[str, Any]] = None) -> str:
    """
    Update manifest to ensure it's cohesive with latest code changes.
    
    This applies all structural and content updates:
    - Assigns UIDs to entries that don't have one
    - Initializes missing entry fields with defaults
    - Sorts entries consistently
    
    Args:
        manifest_path: Manifest file to load and update
        manifest_to_update: If provided, update this manifest instead of loading from file
    
    Returns:
        Path to the updated manifest
    """
    # Load manifest if not provided
    if manifest_to_update is None:
        manifest = load_manifest(manifest_path)
        if manifest is None:
            raise ValueError(f"Manifest file '{manifest_path}' does not exist. Use -u/--update-from-clips to create from clip directory.")
    else:
        manifest = manifest_to_update
    
    # Apply management operations
    assign_uids(manifest)
    initialize_entry_fields(manifest)
    sort_entries(manifest)
    
    # Save the updated manifest
    save_manifest(manifest, manifest_path)
    
    return str(manifest_path.resolve())

def main():
    parser = argparse.ArgumentParser(
        prog="manage_eye_manifest.py",
        description="Manage an eye animation manifest for character clips (Godot ConfigFile format).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s eye_manifest.cfg                          # Update existing manifest
  %(prog)s -u ./clips eye_manifest.cfg               # Generate/update from clips, delete missing
  %(prog)s -u ./clips -d eye_manifest.cfg            # Generate/update from clips and delete missing files
  %(prog)s -u ./clips my_manifest.cfg                # Use custom manifest output path
        """
    )
    
    parser.add_argument(
        "manifest_file",
        help="Path to manifest file to create or update"
    )
    
    parser.add_argument(
        "-u", "--update-from-clips",
        metavar="CLIP_DIR",
        help="Update manifest by scanning CLIP_DIR for character subdirectories with .mov clips. "
             "Filenames are the source of truth; physical files don't need to exist to work with the manifest. "
             "-d/--delete-absent only has effect when this flag is used."
    )
    
    parser.add_argument(
        "-d", "--delete-absent",
        action="store_true",
        help="When used with -u/--update-from-clips: remove entries for files no longer present in clip directory. "
             "Has no effect without -u/--update-from-clips."
    )

    args = parser.parse_args()
    
    manifest_path = Path(args.manifest_file)
    
    try:
        if args.update_from_clips:
            # Update from clips directory
            is_new, result_path = update_manifest_from_clips(
                args.update_from_clips, 
                manifest_path, 
                args.delete_absent
            )
            
            status = "Created new" if is_new else "Updated existing"
            print(f"{status} manifest: {result_path}")
            
        # Normal update operation
        result_path = update_manifest(manifest_path)
        print(f"Updated manifest: {result_path}")
        
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
