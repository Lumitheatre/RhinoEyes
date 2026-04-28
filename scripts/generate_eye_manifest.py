#!/usr/bin/env python3

import argparse
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
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Check version
    if manifest.get("manifest_version") != VERSION:
        raise ValueError(f"Manifest version {manifest.get('manifest_version')} doesn't match script version {VERSION}")
    
    return manifest

def save_manifest(manifest: Dict[str, Any], manifest_path: Path) -> None:
    """Save manifest to JSON file."""
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

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
        manifest = {
            "manifest_version": VERSION,
            "characters": {}
        }
    
    # Process each character directory
    for char_dir in sorted(clip_dir_path.iterdir()):
        if not char_dir.is_dir():
            continue
        
        char_name = char_dir.name
        clips = get_clips_for_character(char_dir)
        
        if not clips:
            continue
        
        # Initialize character in manifest if not present
        if char_name not in manifest["characters"]:
            manifest["characters"][char_name] = []
        
        existing_entries = manifest["characters"][char_name]
        
        # Build new entry list by iterating through clips in alphabetic order
        new_entries = []
        
        for _, clip_name in enumerate(clips):
            file_path = f"res://{char_dir}/{clip_name}"
            
            # Check if this file already exists in manifest
            existing_entry = None
            for entry in existing_entries:
                if entry["file"] == file_path:
                    existing_entry = entry
                    break
            
            if existing_entry is not None:
                # Preserve existing entry without modification
                new_entries.append(existing_entry)
            else:
                # Create new entry with calculated values based on position
                angle, aggro = 0, 0
                new_entries.append({
                    "file": file_path,
                    "aggrivation": aggro,
                    "angle": angle
                })
        
        manifest["characters"][char_name] = new_entries
    
    save_manifest(manifest, manifest_path)
    
    return is_new, str(manifest_path.resolve())

def main():
    parser = argparse.ArgumentParser(
        prog="generate_eye_manifest.py",
        description="Generate or update an eye animation manifest for character clips.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Use current directory and create eye_manifest.json
  %(prog)s ./clips                   # Use ./clips directory and create eye_manifest.json
  %(prog)s ./clips my_manifest.json  # Use ./clips and save to my_manifest.json
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
        default="eye_manifest.json",
        help="Output manifest file path (default: eye_manifest.json)"
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
