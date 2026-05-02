import json
import math
import subprocess
import configparser
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional

from rich.console import Console  # type: ignore

from .constants import FFMPEG_LOG_LEVEL, ACTOR_NS, SHEET_NS, MAX_WORKERS
from .display import TileNormalizationDisplay, SpriteSheetDisplay

# Global executor for normalizing clips across all sheets
_global_executor: Optional[ProcessPoolExecutor] = None

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

class SheetBuilder:
    """Builds sheets defined in the manifest based on manifest attributes. Does not modify the manifest itself, and uses it as a declarative source of truth for the sheet structure and clip metadata.

    By default, rerunning the script will skip existing tiles. Use regenerate_tiles=True to recreate them.
    """
    
    def __init__(self, config, regenerate_tiles=False):
        """Initialize SheetBuilder with a parsed ConfigParser object.
        
        Args:
            config: A configparser.ConfigParser object containing the manifest configuration.
            regenerate_tiles: If True, recreate all tiles. If False (default), skip existing tiles.
        """
        if not isinstance(config, configparser.ConfigParser):
            raise TypeError("config must be a configparser.ConfigParser object")
        
        self.config = config
        self.sheets = {}
        self.actors = []
        self.regenerate_tiles = regenerate_tiles

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
                # Assuming channel is assigned based on actor order or a new key
                # For this script, we'll look for a 'channel' key or default to R/G/B
                channel = self.config.get(section, "channel", fallback="R").strip('"')
                
                clips_raw = self.config.get(section, "clips")
                clips_list = json.loads(clips_raw)
                
                for clip in clips_list:
                    if clip.get("enabled") == "false" or \
                       not clip.get("sheet_id") or clip.get("sheet_id") not in self.sheets or \
                       not clip.get("path"):
                        continue
                    
                    sid = str(clip["sheet_id"])
                    clip["actor_name"] = actor_name
                    clip["channel"] = channel
                    self.sheets[sid]["clips"].append(clip)

    def get_output_tile_filename(self, clip) -> str:
        """Get the output tile filename for a clip.
        
        Args:
            clip: The clip dictionary.
            
        Returns:
            The output tile filename.
        """
        return f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_{clip['channel']}_u{clip['uid']}.mov"
    
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
        output_name = f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_{clip['channel']}_u{clip['uid']}.mov"
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
        
        # 3. Random Phase Shift (frames)
        # We shift by frames rather than seconds for pixel-perfect alignment
        rand_offset_frames = 0 # random.randint(0, frames_per_segment - 1)
        rand_offset_secs = rand_offset_frames / fps
    
        # 4. The "Seam-Free" Filter Chain
        # We apply FPS *after* the speed change to "bake" the frames into the new speed.
        filter_graph = [
            f"[0:v]scale={target_resolution[0]}:{target_resolution[1]},setpts=PTS-STARTPTS[v_scaled]",
            f"[v_scaled]setpts={speed_factor}*PTS[v_sped]",
            f"[v_sped]fps={fps}:round=near[v_fixed_fps]", # Bake the frames here
            f"[v_fixed_fps]loop=loop={loop_count + 1}:size={frames_per_segment}:start=0[v_looped]",
            f"[v_looped]trim=start={rand_offset_secs}:duration={target_duration},setpts=PTS-STARTPTS[v_final]"
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

    def build_sheet(self, sheet_id, tiles_dir: Path, tile_resolution=(420,270), grid=(8,8), duration=30):
        """Step 2: Pack 64 tiles into R, G, B channels of a 4K file.
        
        Args:
            sheet_id: The ID of the sheet to build.
            tiles_dir: Path to the directory containing the normalized tile files.
            tile_resolution: Tuple of (width, height) for individual tiles (strings or integers).
            grid: Tuple of (grid_width, grid_height) for the sheet layout.
            duration: Duration of the sheet in seconds.
        """
        sheet_data = self.sheets[sheet_id]
        clips = sheet_data["clips"]
        output_path = Path(sheet_data["path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert tile_resolution to integers for calculations, keep strings for ffmpeg
        tile_w_int = int(tile_resolution[0]) if isinstance(tile_resolution[0], str) else tile_resolution[0]
        tile_h_int = int(tile_resolution[1]) if isinstance(tile_resolution[1], str) else tile_resolution[1]
        tile_res_str = (str(tile_resolution[0]), str(tile_resolution[1]))

        # Organize by Channel and Slot (2 actors per channel, 32 clips each)
        channels: Dict[str, List[Optional[Path]]] = {"R": [None for _ in range(64)], "G": [None for _ in range(64)], "B": [None for _ in range(64)]}
        
        for clip in clips:
            # Map index: slot 0 uses 0-31, slot 1 uses 32-63
            idx = int(clip["sheet_slot"])
            # Find the intermediate file
            fname = f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_{clip['channel']}_u{clip['uid']}.mov"
            channels[clip["channel"]][idx] = tiles_dir / fname

        # Create "Black" tile for missing slots
        black_tile = tiles_dir / "black.mov"
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

        # 3. Build the Massive Command
        inputs = []
        filter_parts = []
        
        # We will process R, then G, then B
        current_input_idx = 0
    
        # Layout is the same for all 3 grids (8x8)
        grid_w, grid_h = grid
        num_tiles = grid_w * grid_h
        layout = "|".join([f"{(i % grid_w) * tile_w_int}_{(i // grid_w) * tile_h_int}" for i in range(num_tiles)])
    
        all_tiles = []
        # Combine all channels into a single list of tiles for the grid
        # For an 8x8 grid (64 tiles), we can just take the first 64 paths from any channel
        # or logic that fits the user's specific grid requirements.
        # Based on previous logic, we have 64 slots per channel. 
        # Here we just want to pack the existing tiles into a grid.

        # We'll use the 'R' channel's list of 64 slots as the source for the grid.
        for i in range(num_tiles):
            file_path = channels["R"][i] if channels["R"][i] else black_tile
            inputs.extend(["-i", str(file_path)])
            all_tiles.append(f"[{current_input_idx}:v]")
            current_input_idx += 1

        # Stack tiles into the grid
        filter_parts.append(f"{''.join(all_tiles)}xstack=inputs={num_tiles}:layout={layout}[outv]")

        # 4. Execute FFmpeg
        print(f"--- Encoding Grid Sheet: {output_path.name} ---")

        cmd = [
            "ffmpeg", "-y", "-v", FFMPEG_LOG_LEVEL,
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            str(output_path)
        ]
    
        # subprocess.run handles the argument list length automatically
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"\nError building sheet {sheet_id}:")
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
        
        # Get global executor (reuse the same one)
        executor = get_global_executor()
        
        # Collect all futures
        all_futures = {}
        
        # Submit all sheet building jobs
        for sid, data in self.sheets.items():
            tiles_dir = sheet_tiles_dirs[sid]
            num_tiles = len(data["clips"])
            
            # Get sheet parameters
            tile_resolution, grid, duration, fps = self.get_sheet_parameters(sid)
            
            # Calculate resulting sprite sheet resolution
            sheet_w, sheet_h = data["resolution"]
            
            future = executor.submit(
                self.build_sheet,
                sid,
                tiles_dir,
                tile_resolution,
                grid,
                duration
            )
            
            future_id = id(future)
            all_futures[future] = sid
            display.start_job(future_id, sid, data["path"], num_tiles, tile_resolution, (sheet_w, sheet_h), fps)
            display.register_future(future_id, future)
        
        console.print(f"Building {len(self.sheets)} sprite sheets...\n")
        
        # Use Live display for progress tracking
        display.start_display()
        try:
            for future in as_completed(all_futures):
                try:
                    future.result()
                    display.complete_job(id(future))
                except Exception as e:
                    display.print_error(f"Sheet {all_futures[future]}", e)
        finally:
            display.stop_display()
        
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
