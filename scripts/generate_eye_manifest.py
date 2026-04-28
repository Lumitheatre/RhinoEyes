#!/usr/bin/env python3

import argparse
import configparser
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

VERSION = "0.1.0"

def get_clips_for_character(char_dir: Path) -> List[str]:
    """Get sorted list of MP4 clips in character directory."""
    clips = sorted([f.name for f in char_dir.glob("*.mp4")])
    return clips

def load_existing_manifest(manifest_path: Path) -> Optional[Dict[str, Any]]:
    """Load existing manifest, return None if doesn't exist."""
    if not manifest_path.exists():
        return None
    
    config = configparser.ConfigParser()
    config.read(manifest_path)
    
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
    
    # Create a section for each actor
    for actor in sorted(manifest.keys()):
        config.add_section(actor)
        
        # Serialize clips as a JSON array string
        clips_json = json.dumps(manifest[actor], indent=2, separators=(', ', ': '))
        config.set(actor, "clips", clips_json)
    
    with open(manifest_path, 'w') as f:
        config.write(f)

def generate_manifest(clip_dir: str, manifest_file_output: str) -> Tuple[bool, str]:
    """
    Generate or update eye manifest for all characters (idempotent).
    
    Returns:
        Tuple of (is_new: bool, manifest_path: str)
        is_new is True if a new manifest was created, False if updated
    """
    clip_dir_path = Path(clip_dir)
    manifest_path = Path(manifest_file_output)
    
    # Try to load existing manifest
    existing_manifest = load_existing_manifest(manifest_path)
    is_new = existing_manifest is None
    
    if existing_manifest is not None:
        # Update existing manifest
        manifest = existing_manifest
    else:
        # Create new manifest
        manifest = {}
    
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
        
        # Build new entry list by iterating through clips in alphabetic order
        new_entries = []
        
        for _, clip_name in enumerate(clips):
            file_path = f"res://{char_dir}/{clip_name}"
            
            # Check if this file already exists in manifest
            existing_entry = None
            for entry in existing_entries:
                if entry.get("path") == file_path:
                    existing_entry = entry
                    break
            
            if existing_entry is not None:
                # Preserve existing entry without modification
                new_entries.append(existing_entry)
            else:
                # Create new entry with calculated values based on position
                angle, aggrivation = 0, 0
                new_entries.append({
                    "path": file_path,
                    "angle": angle,
                    "aggrivation": aggrivation
                })
        
        manifest[char_name] = new_entries
    
    save_manifest(manifest, manifest_path)
    
    return is_new, str(manifest_path.resolve())

def main():
    parser = argparse.ArgumentParser(
        prog="generate_eye_manifest.py",
        description="Generate or update an eye animation manifest for character clips (Godot ConfigFile format).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Use current directory and create eye_manifest.cfg
  %(prog)s ./clips                   # Use ./clips directory and create eye_manifest.cfg
  %(prog)s ./clips my_manifest.cfg   # Use ./clips and save to my_manifest.cfg
        """
    )
    
    parser.add_argument(
        "clip_dir",
        nargs="?",
        default=".",
        help="Directory containing character subdirectories with MP4 clips (default: current directory)"
    )
    
    parser.add_argument(
        "manifest_file",
        nargs="?",
        default="eye_manifest.cfg",
        help="Output manifest file path (default: eye_manifest.cfg)"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}"
    )
    
    args = parser.parse_args()
    
    try:
        is_new, manifest_path = generate_manifest(args.clip_dir, args.manifest_file)
        status = "Created new" if is_new else "Updated existing"
        print(f"{status} manifest: {manifest_path}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
