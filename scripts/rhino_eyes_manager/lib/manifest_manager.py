"""Core manifest management functionality."""

import configparser
import json
import random
from pathlib import Path
from typing import List, Optional

from .constants import ACTOR_NS, MANIFEST_NS, SHEET_NS, VERSION


class ManifestManager:
    """Manages eye animation manifest for character clips."""

    def __init__(self):
        """Initialize the manifest manager."""
        self.version = VERSION

    def get_clips_for_character(self, char_dir: Path) -> List[str]:
        """Get sorted list of clips in character directory."""
        clips = sorted([f.name for f in char_dir.glob("*.mov")])
        return clips

    def migrate_old_manifest(self, manifest: configparser.ConfigParser) -> configparser.ConfigParser:
        """
        Migrate old manifest format (sections = actor names) to new namespace format.
        Also migrates version from DEFAULT section to manifest: section.

        Old format: [actor_name] with clips = [...], version in DEFAULT
        New format: [actor:actor_name] with clips = [...], version in manifest:

        Modifies manifest in place and returns it.
        """
        new_manifest = configparser.ConfigParser()

        # Create manifest: section with version
        manifest_section = f"{MANIFEST_NS}:"
        new_manifest.add_section(manifest_section)
        new_manifest.set(manifest_section, "version", VERSION)

        # Parse each section - if it doesn't start with a namespace prefix, treat it as old-style actor
        for section in manifest.sections():
            if ":" not in section and section != "DEFAULT":
                # Old format: actor name without namespace prefix
                if manifest.has_option(section, "clips"):
                    new_section = f"{ACTOR_NS}:{section}"
                    new_manifest.add_section(new_section)
                    # Copy all options from old section to new section
                    for key in manifest[section]:
                        new_manifest.set(new_section, key, manifest.get(section, key))

        return new_manifest

    def load_manifest(self, manifest_path: Path) -> Optional[configparser.ConfigParser]:
        """Load existing manifest, return None if doesn't exist."""
        if not manifest_path.exists():
            return None

        manifest = configparser.ConfigParser()
        manifest.read(manifest_path)

        # Check for version in manifest: section (new format)
        manifest_section = f"{MANIFEST_NS}:"
        if manifest.has_section(manifest_section) and manifest.has_option(manifest_section, "version"):
            manifest_version = manifest.get(manifest_section, "version").strip('"')
        # Fall back to DEFAULT section (old format, will fail with migration prompt)
        elif manifest.has_option("DEFAULT", "manifest_version"):
            manifest_version = manifest.get("DEFAULT", "manifest_version")
        else:
            raise ValueError(
                f"Manifest version not found in '{manifest_path}'. "
                f"Expected to find 'version' in section '{manifest_section}' or 'manifest_version' in DEFAULT. "
                f"Use --migrate to convert old format."
            )
            return None

        if manifest_version != VERSION:
            raise ValueError(
                f"Manifest version mismatch. File: {manifest_version}, Expected: {VERSION}. "
                f"Use --migrate to convert old format."
            )

        return manifest

    def create_manifest(self) -> configparser.ConfigParser:
        """
        Create a new manifest with the current version.

        Returns:
            New ConfigParser manifest object with version set
        """
        manifest = configparser.ConfigParser()
        manifest_section = f"{MANIFEST_NS}:"
        manifest.add_section(manifest_section)
        manifest.set(manifest_section, "version", VERSION)
        return manifest

    def save_manifest(self, manifest: configparser.ConfigParser, manifest_path: Path) -> None:
        """Save manifest to ConfigFile (.cfg) format with namespace structure."""
        # Ensure manifest: section exists with version
        manifest_section = f"{MANIFEST_NS}:"
        if not manifest.has_section(manifest_section):
            manifest.add_section(manifest_section)
            manifest.set(manifest_section, "version", f'\"{VERSION}\"')


        with open(manifest_path, "w") as f:
            manifest.write(f)

    def create_entry(self, path: str) -> dict:
        """
        Create a new entry with minimal required fields.
        Only the path is populated; other fields are left for management.

        Args:
            path: Path to the clip file

        Returns:
            A new entry dict with just the path
        """
        return {"path": path}

    def get_sheet_capacity(self, manifest: configparser.ConfigParser, sheet_id: str) -> int:
        """
        Calculate the capacity of a sheet based on its grid dimensions and number of channels.

        Args:
            manifest: The manifest config
            sheet_id: The sheet identifier (e.g., "1" from "sheet:1")

        Returns:
            The total capacity (width * height * num_channels) or 0 if grid not found
        """
        sheet_section = f"{SHEET_NS}:{sheet_id}"
        if not manifest.has_section(sheet_section):
            return 0

        if not manifest.has_option(sheet_section, "grid"):
            return 0

        grid_str = manifest.get(sheet_section, "grid")
        try:
            # Parse grid format "WxH" (e.g., "8x8")
            parts = grid_str.strip('"').split("x")
            if len(parts) == 2:
                width = int(parts[0])
                height = int(parts[1])
                grid_capacity = width * height

                # Multiply by number of channels
                channels = self.get_sheet_channels(manifest, sheet_id)
                return grid_capacity * len(channels)
        except (ValueError, AttributeError):
            pass

        return 0

    def get_sheet_channels(self, manifest: configparser.ConfigParser, sheet_id: str) -> List[str]:
        """
        Get the list of channel names for a sheet.

        Args:
            manifest: The manifest config
            sheet_id: The sheet identifier

        Returns:
            List of channel names (e.g., ["R"] or ["R", "G", "B"]), or ["R"] if not specified
        """
        sheet_section = f"{SHEET_NS}:{sheet_id}"
        if not manifest.has_section(sheet_section):
            return ["R"]  # Default to "R" if not specified

        if not manifest.has_option(sheet_section, "channels"):
            return ["R"]  # Default to "R" if not specified

        channels_str = manifest.get(sheet_section, "channels")
        try:
            # Parse the channels array format: [ "R" ] or [ "R", "G", "B" ]
            # Remove brackets and split
            channels_str = channels_str.strip()
            if channels_str.startswith("[") and channels_str.endswith("]"):
                channels_str = channels_str[1:-1]  # Remove brackets
                channels = [c.strip().strip('"') for c in channels_str.split(",")]
                return [c for c in channels if c]  # Filter out empty strings
        except (ValueError, AttributeError):
            pass

        return ["R"]  # Default to "R" if parsing fails

    def get_sheet_usage(self, manifest: configparser.ConfigParser, sheet_id: str) -> int:
        """
        Count how many clips are currently assigned to a sheet.

        Args:
            manifest: The manifest config
            sheet_id: The sheet identifier

        Returns:
            The number of clips assigned to this sheet
        """
        count = 0
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for clip in clips:
                            if clip.get("sheet_id") == sheet_id:
                                count += 1
                    except json.JSONDecodeError:
                        pass
        return count

    def allocate_clips_to_sheets(self, manifest: configparser.ConfigParser, clear_existing: bool = False) -> None:
        """
        Allocate clips to sheets based on available capacity, with support for channel packing.

        Sequentially assigns sheet_id, sheet_slot, and sheet_channel to clips.
        Allocation order is channel-major, slot-minor: fills all slots in "R" (0-63), then "G" (0-63), etc.
        Clips are assigned to sheets based on available capacity.

        Args:
            manifest: The manifest config to modify in place
            clear_existing: If True, clears all existing sheet_id, sheet_slot, and sheet_channel assignments (destructive).
                           If False, preserves existing assignments and only assigns unassigned clips.

        Unassigned clips (no sheet_id) indicate insufficient capacity.
        """
        # Get list of sheets
        sheets = []
        for section in manifest.sections():
            if section.startswith(f"{SHEET_NS}:"):
                sheet_id = section[len(f"{SHEET_NS}:") :]
                sheets.append(sheet_id)

        if not sheets:
            operation = "reallocation" if clear_existing else "allocation"
            print(f"Warning: No sheets found in manifest. Skipping clip {operation}.")
            return

        sheets.sort()

        # Get sheet info: capacity and channels
        sheet_capacity = {sheet_id: self.get_sheet_capacity(manifest, sheet_id) for sheet_id in sheets}
        sheet_channels = {sheet_id: self.get_sheet_channels(manifest, sheet_id) for sheet_id in sheets}

        # Grid capacity per channel (total capacity / num_channels)
        sheet_grid_capacity = {}
        for sheet_id in sheets:
            num_channels = len(sheet_channels[sheet_id])
            sheet_grid_capacity[sheet_id] = sheet_capacity[sheet_id] // num_channels if num_channels > 0 else 0

        # Initialize sheet usage and allocation tracking
        sheet_usage = {sheet_id: 0 for sheet_id in sheets}
        # Track next slot to fill per sheet per channel
        sheet_next_slot = {sheet_id: {ch: 0 for ch in sheet_channels[sheet_id]} for sheet_id in sheets}

        # If not clearing, count existing assignments
        if not clear_existing:
            for section in manifest.sections():
                if section.startswith(f"{ACTOR_NS}:"):
                    if manifest.has_option(section, "clips"):
                        clips_str = manifest.get(section, "clips")
                        try:
                            clips = json.loads(clips_str)
                            for clip in clips:
                                if "sheet_id" in clip:
                                    sheet_id = clip["sheet_id"]
                                    sheet_usage[sheet_id] += 1
                                    # Update next slot tracking for existing assignments
                                    if "sheet_channel" in clip and "sheet_slot" in clip:
                                        channel = clip["sheet_channel"]
                                        slot = clip["sheet_slot"]
                                        # Track the next available slot
                                        if slot + 1 > sheet_next_slot[sheet_id].get(channel, 0):
                                            sheet_next_slot[sheet_id][channel] = slot + 1
                        except json.JSONDecodeError:
                            pass

        operation = "Reallocating" if clear_existing else "Allocating"
        print(f"{operation} clips to {len(sheets)} sheet(s):")
        for sheet_id in sheets:
            channels_str = ", ".join(sheet_channels[sheet_id])
            cap_str = (
                f"/{sheet_capacity[sheet_id]}"
                if clear_existing
                else f"/{sheet_capacity[sheet_id]} capacity"
            )
            print(f"  Sheet {sheet_id} [{channels_str}]: {sheet_usage[sheet_id]}{cap_str}")

        # Process each actor's clips
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)

                        # Allocate each clip to a sheet
                        for clip in clips:
                            # If clearing, remove existing assignments
                            if clear_existing:
                                if "sheet_id" in clip:
                                    del clip["sheet_id"]
                                if "sheet_slot" in clip:
                                    del clip["sheet_slot"]
                                if "sheet_channel" in clip:
                                    del clip["sheet_channel"]

                            # Skip if already assigned (when not clearing)
                            if not clear_existing and "sheet_id" in clip:
                                continue

                            # Find first sheet with available capacity
                            assigned = False
                            for sheet_id in sheets:
                                if sheet_usage[sheet_id] < sheet_capacity[sheet_id]:
                                    # Find the next available channel and slot
                                    for channel in sheet_channels[sheet_id]:
                                        slot = sheet_next_slot[sheet_id][channel]
                                        if slot < sheet_grid_capacity[sheet_id]:
                                            clip["sheet_id"] = sheet_id
                                            clip["sheet_slot"] = slot
                                            clip["sheet_channel"] = channel
                                            sheet_usage[sheet_id] += 1
                                            sheet_next_slot[sheet_id][channel] += 1
                                            assigned = True
                                            break

                                    if assigned:
                                        break

                            if not assigned:
                                # No space available, leave unassigned
                                pass

                        manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(', ', ': ')))
                    except json.JSONDecodeError:
                        pass

    def get_max_uid(self, manifest: configparser.ConfigParser) -> int:
        """Get the maximum UID currently in the manifest, or -1 if none exist."""
        max_uid = 0

        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for clip in clips:
                            if "uid" in clip:
                                max_uid = max(max_uid, clip["uid"])
                    except json.JSONDecodeError:
                        pass

        return max_uid

    def assign_uids(self, manifest: configparser.ConfigParser) -> None:
        """
        Assign UIDs to all entries that don't have one.
        Uses the maximum existing UID and increments from there.

        Modifies manifest in place.
        """
        next_uid = self.get_max_uid(manifest) + 1

        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for entry in clips:
                            if "uid" not in entry:
                                entry["uid"] = next_uid
                                next_uid += 1
                        manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                    except json.JSONDecodeError:
                        pass

    def initialize_entry_fields(self, manifest: configparser.ConfigParser) -> None:
        """
        Initialize missing fields in entries with default values.
        Ensures all entries have a consistent structure.

        Modifies manifest in place.
        """
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for entry in clips:
                            entry.setdefault("enabled", "true")
                            entry.setdefault("angle", 0)
                            entry.setdefault("aggravation", 0)
                        manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                    except json.JSONDecodeError:
                        pass

    def sort_entries(self, manifest: configparser.ConfigParser) -> None:
        """
        Sort all entries by aggravation, then angle, then path.

        Modifies manifest in place.
        """
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        clips.sort(key=lambda x: (x.get("aggravation", 0), x.get("angle", 0), x.get("path", "")))
                        manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                    except json.JSONDecodeError:
                        pass

    def initialize_loop_offsets(self, manifest: configparser.ConfigParser) -> None:
        """
        Initialize missing loop_offset fields in entries with random values between 0 and 1.
        Only adds loop_offset if it doesn't already exist.

        Modifies manifest in place.
        """
        modified = False
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for entry in clips:
                            if "loop_offset" not in entry:
                                entry["loop_offset"] = f"{random.random():.2f}"
                                modified = True
                        if modified:
                            manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                    except json.JSONDecodeError:
                        pass

    def regenerate_loop_offsets(self, manifest: configparser.ConfigParser) -> None:
        """
        Regenerate loop_offset values for all entries with new random values between 0 and 1.
        Overwrites existing loop_offset values.

        Modifies manifest in place.
        """
        for section in manifest.sections():
            if section.startswith(f"{ACTOR_NS}:"):
                if manifest.has_option(section, "clips"):
                    clips_str = manifest.get(section, "clips")
                    try:
                        clips = json.loads(clips_str)
                        for entry in clips:
                            entry["loop_offset"] = f"{random.random():.2f}"
                        manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                    except json.JSONDecodeError:
                        pass

    def sync_manifest_from_clips(
        self, clip_dir: str, manifest: configparser.ConfigParser, delete_absent: bool = False
    ) -> None:
        """
        Synchronize manifest with clips found in clip_dir.

        This function:
        - Creates new entries for clips not in manifest (just path field)
        - Removes entries for clips that no longer exist (if delete_absent=True)
        - Does NOT modify any other entry fields

        Modifies manifest in place.

        Args:
            clip_dir: Directory containing character subdirectories with .mov clips
            manifest: The manifest to synchronize
            delete_absent: If True, remove entries for files not found on disk
        """
        clip_dir_path = Path(clip_dir)

        # If delete_absent flag is set, remove entries for files not found on disk
        if delete_absent:
            print("Removing entries for files no longer present in clip directory...")
            for section in list(manifest.sections()):
                if section.startswith(f"{ACTOR_NS}:"):
                    if manifest.has_option(section, "clips"):
                        clips_str = manifest.get(section, "clips")
                        try:
                            clips = json.loads(clips_str)
                            clips[:] = [entry for entry in clips if Path(entry.get("path", "")).exists()]
                            if clips:
                                manifest.set(section, "clips", json.dumps(clips, indent=2, separators=(", ", ": ")))
                            else:
                                manifest.remove_section(section)
                        except json.JSONDecodeError:
                            pass

        # Process each character directory
        for char_dir in sorted(clip_dir_path.iterdir()):
            if not char_dir.is_dir():
                continue

            char_name = char_dir.name
            clips_list = self.get_clips_for_character(char_dir)

            if not clips_list:
                continue

            actor_section = f"{ACTOR_NS}:{char_name}"

            # Load existing clips for this actor
            existing_clips = []
            if manifest.has_section(actor_section) and manifest.has_option(actor_section, "clips"):
                clips_str = manifest.get(actor_section, "clips")
                try:
                    existing_clips = json.loads(clips_str)
                except json.JSONDecodeError:
                    existing_clips = []

            new_clips = []

            # Process each clip file
            for clip_name in clips_list:
                file_path = f"{char_dir}/{clip_name}"

                # Check if this file already exists in manifest
                existing_entry = None
                for entry in existing_clips:
                    if entry.get("path") == file_path:
                        existing_entry = entry
                        break

                if existing_entry:
                    # Preserve existing entry
                    new_clips.append(existing_entry)
                else:
                    # Create new entry (just path, other fields added during management)
                    new_clips.append(self.create_entry(file_path))

            if not delete_absent:
                # Add back any existing entries that reference missing files
                for entry in existing_clips:
                    entry_path = entry.get("path", "")
                    # Check if this entry is not in the new list
                    if not any(e.get("path") == entry_path for e in new_clips):
                        new_clips.append(entry)

            # Ensure section exists
            if not manifest.has_section(actor_section):
                manifest.add_section(actor_section)

            # Save updated clips
            manifest.set(actor_section, "clips", json.dumps(new_clips, indent=2, separators=(", ", ": ")))

    def update_manifest_from_clips(
        self, clip_dir: str, manifest: configparser.ConfigParser, delete_absent: bool = False
    ) -> None:
        """
        Update manifest based on clips in directory.

        Scans clip_dir for character subdirectories and .mov files, and syncs the manifest.
        Does NOT save the manifest to disk; caller is responsible for that.

        Args:
            clip_dir: Directory containing character subdirectories with .mov clips
            manifest: ConfigParser manifest object to update in-place
            delete_absent: If True, remove entries for files that no longer exist in clip_dir
        """
        # Sync with clips directory
        self.sync_manifest_from_clips(clip_dir, manifest, delete_absent)

    def update_manifest(self, manifest_path: Path, manifest: Optional[configparser.ConfigParser] = None) -> str:
        """
        Update manifest to ensure it's cohesive with latest code changes.

        This applies all structural and content updates:
        - Assigns UIDs to entries that don't have one
        - Initializes missing entry fields with defaults
        - Initializes missing loop_offset values
        - Sorts entries consistently

        Args:
            manifest_path: Manifest file to load and update
            manifest: Optional ConfigParser manifest object. If not provided, loads from manifest_path

        Returns:
            Path to the updated manifest
        """
        # Load manifest if not provided
        if manifest is None:
            manifest = self.load_manifest(manifest_path)
            if manifest is None:
                raise ValueError(
                    f"Manifest file '{manifest_path}' does not exist. "
                    f"Use -u/--update-from-clips to create from clip directory."
                )

        # Apply management operations
        self.assign_uids(manifest)
        self.initialize_entry_fields(manifest)
        self.initialize_loop_offsets(manifest)
        self.sort_entries(manifest)

        # Save the updated manifest
        self.save_manifest(manifest, manifest_path)

        return str(manifest_path.resolve())
