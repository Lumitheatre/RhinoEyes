import json
import math
import subprocess
import configparser
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Optional

from rich.console import Console  # type: ignore

from .constants import FFMPEG_LOG_LEVEL, ACTOR_NS, SHEET_NS, MAX_WORKERS
from .display import TileNormalizationDisplay, SpriteSheetDisplay

# Global executor for normalizing clips across all sheets
_global_executor: Optional[ProcessPoolExecutor] = None

# Global display for sheet generation progress tracking
_global_display: Optional[SpriteSheetDisplay] = None

def get_global_executor() -> ProcessPoolExecutor:
    """Get or create the global executor for tile normalization.

    Returns:
        The global ProcessPoolExecutor instance.
    """
    global _global_executor
    if _global_executor is None:
        _global_executor = ProcessPoolExecutor(max_workers=MAX_WORKERS)
    return _global_executor

def shutdown_global_executor() -> None:
    """Shutdown the global executor."""
    global _global_executor
    if _global_executor is not None:
        _global_executor.shutdown(wait=True)
        _global_executor = None

def get_global_display() -> Optional[SpriteSheetDisplay]:
    """Get the global display instance if it exists.

    Returns:
        The global SpriteSheetDisplay instance, or None if not set.
    """
    global _global_display
    return _global_display

def set_global_display(display: Optional[SpriteSheetDisplay]) -> None:
    """Set the global display instance.

    Args:
        display: The SpriteSheetDisplay instance to use globally, or None to clear.
    """
    global _global_display
    _global_display = display

class SheetBuilder:
    """Builds sheets defined in the manifest based on manifest attributes. Does not modify the manifest itself, and uses it as a declarative source of truth for the sheet structure and clip metadata.

    By default, rerunning the script will skip existing tiles. Use regenerate_tiles=True to recreate them.
    """

    def __init__(self, config, regenerate_tiles=False, regenerate_channel_grids=False):
        """Initialize SheetBuilder with a parsed ConfigParser object.

        Args:
            config: A configparser.ConfigParser object containing the manifest configuration.
            regenerate_tiles: If True, recreate all tiles. If False (default), skip existing tiles.
            regenerate_channel_grids: If True, regenerate intermediate channel grids. If False (default), skip existing grids.
        """
        if not isinstance(config, configparser.ConfigParser):
            raise TypeError("config must be a configparser.ConfigParser object")

        self.config = config
        self.sheets = {}
        self.actors = []
        self.regenerate_tiles = regenerate_tiles
        self.regenerate_channel_grids = regenerate_channel_grids

    def get_sheet_tiles_dir(self, sheet_path: str) -> Path:
        """Get the tiles directory for a sheet based on its output path.

        Args:
            sheet_path: The output path of the sheet file.

        Returns:
            Path to the sheet-specific tiles directory.
        """
        sheet_output = Path(sheet_path)
        sheet_name = sheet_output.stem  # Get filename without extension
        tiles_dir = sheet_output.parent / f"{sheet_name}_tiles"
        tiles_dir.mkdir(parents=True, exist_ok=True)
        return tiles_dir

    def parse_manifest(self):
        # 1. Load Sheets
        sheet_prefix = f"{SHEET_NS}:"
        for section in self.config.sections():
            if section.startswith(sheet_prefix):
                sid = section.split(":")[1]
                self.sheets[sid] = {
                    "path": self.config.get(section, "path").strip('"'),
                    "duration": self.config.getfloat(section, "loop_duration"),
                    "resolution": tuple(map(int, self.config.get(section, "resolution").strip('"').split("x"))),
                    "clips": [] # To be filled
                }

        # 2. Load Actors and map clips to sheets
        actor_prefix = f"{ACTOR_NS}:"
        for section in self.config.sections():
            if section.startswith(actor_prefix):
                actor_name = section.split(":")[1]

                clips_raw = self.config.get(section, "clips")
                clips_list = json.loads(clips_raw)

                for clip in clips_list:
                    if clip.get("enabled") == "false" or \
                       not clip.get("sheet_id") or clip.get("sheet_id") not in self.sheets or \
                       not clip.get("path"):
                        continue

                    sid = str(clip["sheet_id"])
                    clip["actor_name"] = actor_name
                    self.sheets[sid]["clips"].append(clip)

    def get_output_tile_filename(self, clip) -> str:
        """Get the output tile filename for a clip.

        Args:
            clip: The clip dictionary.

        Returns:
            The output tile filename.
        """
        return f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_{clip['sheet_channel']}_u{clip['uid']}.mov"

    def get_sheet_parameters(self, sheet_id: str) -> tuple:
        """Calculate sheet parameters including tile resolution and grid dimensions.

        Args:
            sheet_id: The sheet ID.

        Returns:
            Tuple of (tile_resolution, grid_dimensions, duration, fps) where:
                - tile_resolution is a tuple of (width, height) as strings
                - grid_dimensions is a tuple of (grid_w, grid_h) as integers
                - duration is a float
                - fps is an integer (defaults to 30 if not specified)
        """
        sheet_section = f"{SHEET_NS}:{sheet_id}"
        grid_str = self.config.get(sheet_section, "grid", fallback="8x8").strip('"')
        grid_w, grid_h = map(int, grid_str.split("x"))

        sheet_data = self.sheets[sheet_id]
        sheet_w, sheet_h = sheet_data["resolution"]
        duration = sheet_data["duration"]
        fps = self.config.getint(sheet_section, "fps", fallback=30)

        tile_w = sheet_w // grid_w
        tile_h = sheet_h // grid_h
        tile_resolution = (str(tile_w), str(tile_h))

        return tile_resolution, (grid_w, grid_h), duration, fps

    def normalize_clip_to_sheet(self, clip, target_duration, output_dir, target_resolution, fps=30):
        """Take a full resolution clip, and produce a sheet tile at the expected resolution and of the expected duration, perfectly looped.

        Args:
            clip: The clip dictionary.
            target_duration: Target duration for the tile.
            output_dir: Output directory for the tile.
            target_resolution: Target resolution tuple.
            fps: Frames per second for the output tile (default 30).

        Returns:
            Tuple of (output_path, clip_uid) to allow tracking in the caller.
        """

        input_path = Path(clip["path"])
        if not input_path.exists():
            raise FileNotFoundError(f"Missing source: {input_path}")

        # Unique ID for the intermediate file
        # Format: sheet_slot_channel_uid.mov
        output_name = f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_{clip['sheet_channel']}_u{clip['uid']}.mov"
        output_path = output_dir / output_name

        # Skip if tile exists and regenerate_tiles is False
        if output_path.exists() and not self.regenerate_tiles:
            return output_path, clip['uid']

        # 1. Get exact duration
        try:
            probe = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)
            ], stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as e:
            print(f"\nError getting duration for clip {clip['uid']}:")
            print(f"Input: {input_path}")
            print(f"Error output: {e.stderr}")
            raise

        probe = probe.strip()

        # Normalize duration: greedily pack the clip to the target duration an integer amount of times, then use speed to fix any remainder. This minimizes the speed adjustment and preserves quality.

        orig_dur = max(float(probe), 0.1)

        # 2. Frame-Perfect Math
        # Calculate how many times it fits in the 30s window
        total_target_frames = int(target_duration * fps)
        loop_count = max(1, round(target_duration / orig_dur))

        # Calculate the exact number of frames each loop segment needs to be
        # We use ceil to ensure we slightly over-fill the 30s before the final trim
        frames_per_segment = math.ceil(total_target_frames / loop_count)
        new_seg_dur = frames_per_segment / fps

        # Speed Factor: (New Duration / Old Duration)
        # If we want to fit 10s into 5s, factor is 0.5 (Speed Up)
        speed_factor = new_seg_dur / orig_dur

        # 3. Loop Phase Shift based on loop_offset
        # Get loop_offset from clip (default to 0 if not present)
        # loop_offset is a factor between 0 and 1 representing the phase shift
        # 0 = no shift, 0.5 = start halfway through the loop
        loop_offset = float(clip.get("loop_offset", 0))

        # Calculate the offset in seconds based on the loop phase
        # We shift by a fraction of one loop segment
        offset_secs = loop_offset * new_seg_dur

        # Convert to frames for pixel-perfect alignment if needed
        offset_frames = round(offset_secs * fps)
        offset_secs = offset_frames / fps

        # 4. The "Seam-Free" Filter Chain
        # We apply FPS *after* the speed change to "bake" the frames into the new speed.
        filter_graph = [
            f"[0:v]scale={target_resolution[0]}:{target_resolution[1]},setpts=PTS-STARTPTS[v_scaled]",
            f"[v_scaled]setpts={speed_factor}*PTS[v_sped]",
            f"[v_sped]fps={fps}:round=near[v_fixed_fps]", # Bake the frames here
            f"[v_fixed_fps]loop=loop={loop_count + 1}:size={frames_per_segment}:start=0[v_looped]",
            f"[v_looped]trim=start={offset_secs}:duration={target_duration},setpts=PTS-STARTPTS[v_final]"
        ]

        cmd = [
            "ffmpeg", "-y", "-v", FFMPEG_LOG_LEVEL,
            "-i", str(input_path),
            "-filter_complex", ";".join(filter_graph),
            "-map", "[v_final]",
            "-r", str(fps),
            "-c:v", "prores_ks", "-profile:v", "4",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

        return output_path, clip['uid']

    @staticmethod
    def _build_channel_grid(
        channel,
        tiles_for_channel,
        intermediate_path,
        layout,
        keyint,
        sheet_id
    ):
        """Build a single channel grid as an intermediate file.

        This method is designed to be run in parallel with other channel builds.

        Args:
            channel: Channel identifier ('R', 'G', or 'B')
            tiles_for_channel: List of tile paths for this channel
            intermediate_path: Output path for the intermediate file
            layout: FFmpeg xstack layout string
            keyint: Keyframe interval
            sheet_id: Sheet identifier for error messages

        Returns:
            Path to the created intermediate file

        Raises:
            subprocess.CalledProcessError: If FFmpeg encoding fails
        """
        # Build inputs list
        inputs = []
        for tile_path in tiles_for_channel:
            inputs.extend(["-i", str(tile_path)])

        # Build xstack filter with desaturation
        input_labels = ""
        filter_parts = []
        for tile_idx in range(len(tiles_for_channel)):
            desaturated_label = f"[d{tile_idx}]"
            filter_parts.append(f"[{tile_idx}:v]hue=s=0{desaturated_label}")
            input_labels += desaturated_label

        # Create xstack and format to grayscale
        filter_parts.append(f"{input_labels}xstack=inputs={len(tiles_for_channel)}:layout={layout}[v]")
        filter_parts.append("[v]format=gray[out]")

        filter_complex = ";".join(filter_parts)

        # Encode to near-lossless intermediate using ultrafast preset
        cmd = [
            "ffmpeg", "-y", "-v", FFMPEG_LOG_LEVEL,
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "10",
            "-pix_fmt", "gray",
            "-g", str(keyint),
            "-keyint_min", str(keyint),
            "-sc_threshold", "0",
            "-x264-params", f"keyint={keyint}",
            str(intermediate_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = (
                f"Error building {channel} channel grid for sheet {sheet_id}:\n"
                f"Output path: {intermediate_path}\n"
                f"Error output: {result.stderr}"
            )
            raise RuntimeError(error_msg)

        return intermediate_path

    def build_sheet(self, sheet_id, tiles_dir: Path, tile_resolution=(420,270), grid=(8,8), duration=30, fps=30):
        """Step 2: Pack tiles into R, G, B channels of a 4K file with channel multiplexing.

        Uses a two-stage build process:
        1. Build intermediate channel grids (R, G, B) in parallel using lossless encoding
        2. Merge the channel grids into final output using mergeplanes

        This approach is faster, more memory efficient, and produces better quality output
        than the previous single-stage approach.

        Args:
            sheet_id: The ID of the sheet to build.
            tiles_dir: Path to the directory containing the normalized tile files.
            tile_resolution: Tuple of (width, height) for individual tiles (strings or integers).
            grid: Tuple of (grid_width, grid_height) for the sheet layout.
            duration: Duration of the sheet in seconds.
            fps: Frames per second for the output video.
        """
        sheet_data = self.sheets[sheet_id]
        clips = sheet_data["clips"]
        output_path = Path(sheet_data["path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert tile_resolution to integers for calculations
        tile_w_int = int(tile_resolution[0]) if isinstance(tile_resolution[0], str) else tile_resolution[0]
        tile_h_int = int(tile_resolution[1]) if isinstance(tile_resolution[1], str) else tile_resolution[1]
        tile_res_str = (str(tile_resolution[0]), str(tile_resolution[1]))

        # Organize by Channel and Slot
        grid_w, grid_h = grid
        num_slots_per_channel = grid_w * grid_h

        channels_dict = {}
        for clip in clips:
            channel = clip.get("sheet_channel", "R")
            if channel not in channels_dict:
                channels_dict[channel] = [None for _ in range(num_slots_per_channel)]

            slot = int(clip["sheet_slot"])
            fname = f"s{clip['sheet_id']}_slot{slot}_{channel}_u{clip['uid']}.mov"
            channels_dict[channel][slot] = tiles_dir / fname

        # Create "Black" tile for missing slots
        black_tile = tiles_dir / "black.mov"
        if not black_tile.exists():
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={'x'.join(tile_res_str)}:d={duration}",
                "-c:v", "prores_ks", str(black_tile)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"\nError creating black tile for Sheet {sheet_id}:")
                print(f"Command: {' '.join(cmd)}")
                print(f"Error output: {result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

        # Process only RGB channels (skip A)
        active_channels = sorted([ch for ch in channels_dict.keys() if ch in ['R', 'G', 'B']])
        if not active_channels:
            active_channels = ['R']  # Default to R if no channels specified

        # Ensure we have R, G, B in order if they exist
        rgb_channels = [ch for ch in ['R', 'G', 'B'] if ch in active_channels]

        # Layout string for grid positioning
        layout = "|".join([f"{(i % grid_w) * tile_w_int}_{(i // grid_w) * tile_h_int}" for i in range(num_slots_per_channel)])

        # Set keyint to fps
        keyint = fps

        # === STAGE 1: Build intermediate channel grids in parallel ===
        intermediate_dir = tiles_dir / "_intermediates"
        intermediate_dir.mkdir(exist_ok=True)

        intermediate_paths = {}

        # Collect channels that need to be built
        channels_to_build = []
        for channel in rgb_channels:
            intermediate_path = intermediate_dir / f"channel_{channel}.mp4"
            intermediate_paths[channel] = intermediate_path

            # Skip if exists and regeneration not requested
            if intermediate_path.exists() and not self.regenerate_channel_grids:
                # Silently use existing - no need to log
                pass
            else:
                channels_to_build.append(channel)

        # Build channels in parallel using the global executor
        channel_futures = {}
        if channels_to_build:
            from concurrent.futures import as_completed

            executor = get_global_executor()

            for channel in channels_to_build:
                tiles_for_channel = channels_dict.get(channel, [None] * num_slots_per_channel)
                # Ensure all slots are filled (use black tile for empty slots)
                tiles_for_channel = [t if t else black_tile for t in tiles_for_channel]

                intermediate_path = intermediate_paths[channel]

                # Submit the channel grid build job
                future = executor.submit(
                    self._build_channel_grid,
                    channel,
                    tiles_for_channel,
                    intermediate_path,
                    layout,
                    keyint,
                    sheet_id
                )
                channel_futures[future] = {
                    'channel': channel,
                    'path': intermediate_path,
                    'sheet_id': sheet_id
                }

                # Register with global display if available
                display = get_global_display()
                if display is not None:
                    future_id = id(future)
                    display.start_channel_job(future_id, sheet_id, channel, intermediate_path)
                    display.register_channel_future(future_id, future)

            # Wait for all channel grids to complete
            for future in as_completed(channel_futures):
                try:
                    future.result()  # Actually wait for and get the result
                    # Mark channel job as complete in display
                    display = get_global_display()
                    if display is not None:
                        display.complete_channel_job(id(future))
                except Exception as e:
                    display = get_global_display()
                    if display is not None:
                        display.complete_channel_job(id(future))
                    raise

        # === STAGE 2: Merge channel grids into final output ===
        if len(rgb_channels) != 3:
            raise ValueError(
                f"Unsupported channel configuration for Sheet {sheet_id}: {rgb_channels}. "
                f"All three R, G, B channels are required for mergeplanes."
            )

        # Build inputs for mergeplanes (must be in R, G, B order)
        merge_inputs = []
        for channel in ['R', 'G', 'B']:
            if channel not in intermediate_paths:
                raise ValueError(f"Missing {channel} channel for sheet {sheet_id}")
            merge_inputs.extend(["-i", str(intermediate_paths[channel])])

        # mergeplanes command
        # 0x001020 means: Y from input 0, U from input 1 (plane 0), V from input 2 (plane 0)
        cmd = [
            "ffmpeg", "-y", "-v", FFMPEG_LOG_LEVEL,
            *merge_inputs,
            "-filter_complex", "[0:v][1:v][2:v]mergeplanes=0x001020:yuv444p[out]",
            "-map", "[out]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-g", str(keyint),
            "-keyint_min", str(keyint),
            "-sc_threshold", "0",
            "-pix_fmt", "yuv444p",
            "-colorspace", "bt709",
            "-color_range", "pc",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"\nError merging channels for sheet {sheet_id}:")
            print(f"Output path: {output_path}")
            print(f"Error output: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

    def normalize_all_tiles(self, console: Console) -> Dict[str, Path]:
        """Normalize all clips to tiles in parallel.

        Args:
            console: Console instance for output.

        Returns:
            Dictionary mapping sheet IDs to their tiles directories.
        """
        # Calculate total clips across all sheets for display
        total_clips_all = sum(len(data["clips"]) for data in self.sheets.values())

        if total_clips_all == 0:
            console.print("[yellow]No clips to process[/yellow]")
            return {}

        # Single display instance for all sheets
        display = TileNormalizationDisplay(total_clips_all, console)

        # Get global executor (will be created if not already exists)
        executor = get_global_executor()

        # Collect all futures and their metadata
        all_futures = {}
        sheet_tiles_dirs = {}  # Map to get tiles_dir from clip later

        # Submit all normalization jobs for all sheets
        for sid, data in self.sheets.items():
            console.print(f"Queuing clips for Sheet {sid}...")

            # Get sheet-specific tiles directory
            tiles_dir = self.get_sheet_tiles_dir(data['path'])
            sheet_tiles_dirs[sid] = tiles_dir

            # Get sheet parameters (tile resolution, grid, duration, fps)
            target_res, grid, duration, fps = self.get_sheet_parameters(sid)

            for c in data["clips"]:
                # Pre-calculate output tile path for display
                output_tile_filename = self.get_output_tile_filename(c)
                output_tile_path = tiles_dir / output_tile_filename

                future = executor.submit(
                    self.normalize_clip_to_sheet,
                    c,
                    duration,
                    tiles_dir,
                    target_res,
                    fps
                )

                future_id = id(future)
                all_futures[future] = c
                display.start_job(future_id, c["uid"], c["sheet_id"], c["path"], str(output_tile_path))
                display.register_future(future_id, future)

        console.print(f"\nProcessing {total_clips_all} clips across {len(self.sheets)} sheets...\n")

        # Use Live display for progress tracking
        display.start_display()
        try:
            for future in as_completed(all_futures):
                try:
                    future.result()
                    display.complete_job(id(future))
                except Exception as e:
                    display.print_error(all_futures[future]['uid'], e)
        finally:
            display.stop_display()

        # Print summary line only
        console.print(display.print_summary())
        console.print()

        return sheet_tiles_dirs

    def build_all_sheets(self, sheet_tiles_dirs: Dict[str, Path], console: Console) -> None:
        """Build all sprite sheets in parallel.

        Args:
            sheet_tiles_dirs: Dictionary mapping sheet IDs to their tiles directories.
            console: Console instance for output.
        """
        if not self.sheets:
            console.print("[yellow]No sheets to build[/yellow]")
            return

        # Create display for sheet generation
        display = SpriteSheetDisplay(len(self.sheets), console)

        # Set as global display so build_sheet can access it
        set_global_display(display)

        console.print(f"Building {len(self.sheets)} sprite sheets...\n")

        # Use Live display for progress tracking
        display.start_display()
        try:
            # Build sheets sequentially (channel grids within each sheet are parallel)
            for sid, data in self.sheets.items():
                tiles_dir = sheet_tiles_dirs[sid]
                num_tiles = len(data["clips"])

                # Get sheet parameters
                tile_resolution, grid, duration, fps = self.get_sheet_parameters(sid)

                # Calculate resulting sprite sheet resolution
                sheet_w, sheet_h = data["resolution"]

                # Create a pseudo-future ID for display tracking
                pseudo_future_id = id(sid)  # Use sheet_id's id as a unique identifier

                # Register sheet job with display
                display.start_job(pseudo_future_id, sid, data["path"], num_tiles, tile_resolution, (sheet_w, sheet_h), fps)

                # Mark as "running" immediately since we're executing it now
                if pseudo_future_id in display.in_progress:
                    display.in_progress[pseudo_future_id]["actual_start_recorded"] = True
                    display.start_times[pseudo_future_id] = time.time()

                try:
                    # Build the sheet (this will handle channel parallelism internally)
                    self.build_sheet(
                        sid,
                        tiles_dir,
                        tile_resolution,
                        grid,
                        duration,
                        fps
                    )
                    display.complete_job(pseudo_future_id)
                except Exception as e:
                    display.complete_job(pseudo_future_id)
                    display.print_error(f"Sheet {sid}", e)
                    raise
        finally:
            display.stop_display()
            # Clear global display
            set_global_display(None)

        # Print summary
        console.print(display.print_summary())
        console.print()

    def run(self):
        """Run the complete sheet building pipeline: parse, normalize tiles, build sheets."""
        self.parse_manifest()
        console = Console()

        try:
            # Step 1: Normalize all tiles
            sheet_tiles_dirs = self.normalize_all_tiles(console)

            if not sheet_tiles_dirs:
                return

            # Step 2: Build all sheets
            self.build_all_sheets(sheet_tiles_dirs, console)

        finally:
            # Ensure executor is cleanly shutdown when all sheets are done
            shutdown_global_executor()

if __name__ == "__main__":
    raise RuntimeError("SheetBuilder must be called through rhino_eyes_manager CLI with --build-sheets flag")
