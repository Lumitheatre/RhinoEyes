import json
import math
import subprocess
import configparser
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, Optional, Set, List, Iterable, Tuple

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
    """Builds sheets defined in the manifest based on manifest attributes.

    Pipeline:
      1) Normalize source clips into per-sheet "tile" MOVs
      2) Pack tiles into sprite sheet video files

    This builder is dependency-aware:
      - Tiles are regenerated only when needed (missing, explicitly forced, or source clip is newer)
      - Sheets are regenerated only when needed (missing or any dependent tile is newer)

    Bulk rebuilds are supported via `regenerate_all=True`.
    """

    def __init__(
        self,
        config,
        regenerate_tiles: Optional[Set[str]] = None,
        ignore_changed_tiles: bool = False,
        regenerate_all: bool = False,
        sequential: bool = True,
    ):
        """Initialize SheetBuilder with a parsed ConfigParser object.

        Args:
            config: A configparser.ConfigParser object containing the manifest configuration.
            regenerate_tiles: Optional set of *source clip filenames* (case-insensitive) to force-regenerate.
                Matching is done against both the source filename (e.g. "blink.mov") and the stem (e.g. "blink").
            ignore_changed_tiles: If True, disable modified-time dependency checks and only regenerate missing tiles/sheets
                (plus any explicitly forced via regenerate_tiles/regenerate_all).
            regenerate_all: If True, force regeneration of all tiles and all sheets.
            sequential: If True (default), build sheets sequentially. If False, build in parallel.
        """
        if not isinstance(config, configparser.ConfigParser):
            raise TypeError("config must be a configparser.ConfigParser object")

        self.config = config
        self.sheets: Dict[str, dict] = {}
        self.actors: List[str] = []

        # Regeneration behavior
        self.regenerate_tiles: Set[str] = {s.strip().lower() for s in (regenerate_tiles or set()) if s.strip()}
        self.ignore_changed_tiles = ignore_changed_tiles
        self.regenerate_all = regenerate_all
        self.sequential = sequential

        # For reporting: which forced tile names actually matched something in the manifest
        self._matched_regenerate_tile_keys: Set[str] = set()

        # Per-run stats (populated by `run()`)
        self._last_tile_stats: Dict[str, int] = {}
        self._last_sheet_stats: Dict[str, int] = {}

        # Sheets impacted by tile normalization this run (used to force dependent sheet rebuild)
        self._sheets_with_tile_work: Set[str] = set()

    def get_sheet_tiles_dir(self, sheet_path: str, sheet_id: Optional[str] = None) -> Path:
        """Get the tiles directory for a sheet based on its output path.
        
        If the manifest sheet entry specifies an intermediates_path attribute,
        the tiles directory will be placed there instead of the sheet path parent.

        Args:
            sheet_path: The output path of the sheet file.
            sheet_id: Optional sheet ID to look up intermediates_path in config.

        Returns:
            Path to the sheet-specific tiles directory.
        """
        sheet_output = Path(sheet_path)
        sheet_name = sheet_output.stem
        
        base_dir = sheet_output.parent
        if sheet_id:
            sheet_section = f"{SHEET_NS}:{sheet_id}"
            try:
                intermediates_path = self.config.get(sheet_section, "intermediates_path", fallback=None)
                if intermediates_path:
                    intermediates_path = intermediates_path.strip('"')
                    base_dir = Path(intermediates_path)
            except (configparser.NoSectionError, configparser.NoOptionError):
                pass
        
        tiles_dir = base_dir / f"{sheet_name}_tiles"
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
        return f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_u{clip['uid']}.mov"

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

    @staticmethod
    def _mtime(path: Path) -> float:
        """Safe mtime read; returns 0.0 if the file does not exist."""
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _clip_matches_regenerate_list(self, clip: dict) -> bool:
        if not self.regenerate_tiles:
            return False

        src = Path(clip["path"])
        keys = {src.name.lower(), src.stem.lower()}
        hits = self.regenerate_tiles.intersection(keys)
        if hits:
            self._matched_regenerate_tile_keys.update(hits)
            return True
        return False

    def normalize_clip_to_sheet(self, clip, target_duration, output_dir, target_resolution, fps=30, force: bool = False):
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
        # Format: sheet_slot_uid.mov
        output_name = f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_u{clip['uid']}.mov"
        output_path = output_dir / output_name

        # Skip if tile exists and we weren't asked/forced to rebuild it
        if output_path.exists() and not force:
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

        # 3. Phase Shift (frames)
        # We shift by frames rather than seconds for pixel-perfect alignment
        # loop_offset is a value between 0 and 1 that represents how far through the loop to start
        loop_offset = clip.get("loop_offset", 0.0)
        rand_offset_frames = int(loop_offset * frames_per_segment)
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

    def build_sheet(self, sheet_id, tiles_dir: Path, tile_resolution=(420,270), grid=(8,8), duration=30, fps=30):
        """Step 2: Pack tiles into a grid sprite sheet.

        Args:
            sheet_id: The ID of the sheet to build.
            tiles_dir: Path to the directory containing the normalized tile files.
            tile_resolution: Tuple of (width, height) for individual tiles (strings or integers).
            grid: Tuple of (grid_width, grid_height) for the sheet layout.
            duration: Duration of the sheet in seconds.
            fps: Frames per second for the sheet.
        """
        sheet_data = self.sheets[sheet_id]
        clips = sheet_data["clips"]
        output_path = Path(sheet_data["path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert tile_resolution to integers for calculations, keep strings for ffmpeg
        tile_w_int = int(tile_resolution[0]) if isinstance(tile_resolution[0], str) else tile_resolution[0]
        tile_h_int = int(tile_resolution[1]) if isinstance(tile_resolution[1], str) else tile_resolution[1]
        tile_res_str = (str(tile_resolution[0]), str(tile_resolution[1]))

        # Collect all tiles based on sheet slot
        tiles_by_slot: Dict[int, Path] = {}

        for clip in clips:
            # Map index: slot index determines position in grid
            idx = int(clip["sheet_slot"])
            # Find the intermediate file
            fname = f"s{clip['sheet_id']}_slot{clip['sheet_slot']}_u{clip['uid']}.mov"
            tiles_by_slot[idx] = tiles_dir / fname

        # Create "Black" tile for missing slots
        black_tile = tiles_dir / "black.mov"
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={'x'.join(tile_res_str)}:d={duration}:r={fps}",
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

        # Layout is the same for all tiles
        current_input_idx = 0
        grid_w, grid_h = grid
        num_tiles = grid_w * grid_h
        layout = "|".join([f"{(i % grid_w) * tile_w_int}_{(i // grid_w) * tile_h_int}" for i in range(num_tiles)])

        all_tiles = []
        # Combine all tiles into a single list for the grid
        # Sheet capacity is determined by grid product (e.g., 8x8 = 64 tiles)
        for i in range(num_tiles):
            file_path = tiles_by_slot.get(i, black_tile)
            inputs.extend(["-i", str(file_path)])
            all_tiles.append(f"[{current_input_idx}:v]")
            current_input_idx += 1

        # Stack tiles into the grid
        filter_parts.append(f"{''.join(all_tiles)}xstack=inputs={num_tiles}:layout={layout}[outv]")

        # 4. Execute FFmpeg with H.264 encoding optimized for ROG Ally hardware decoding in Godot
        # Godot (via plugins) generally handles H.264 better than H.265 due to missing OS HEVC extensions
        # Profile High, Level 4.2 provides excellent hardware acceleration on RDNA 2 GPU
        # -tune fastdecode simplifies the stream to ensure smooth playback
        print(f"--- Encoding Grid Sheet: {output_path.name} ---")

        cmd = [
            "ffmpeg", "-y", "-v", FFMPEG_LOG_LEVEL,
            *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", "[outv]",
            "-r", str(fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-level", "4.2",
            "-preset", "fast",
            "-crf", "20",
            "-tune", "fastdecode",
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
        """Normalize clips into tiles (incremental).

        Tiles are queued only when needed:
          - missing tile output
          - `regenerate_all` is set
          - source filename matches `regenerate_tiles`
          - (default) source clip is newer than the tile (mtime)

        Set `ignore_changed_tiles=True` to disable the mtime check and use existence-only incremental behavior.

        Returns a mapping of sheet_id -> tiles_dir for *all* sheets.
        """
        # Reset per-run impact tracking
        self._sheets_with_tile_work = set()

        total_clips_all = sum(len(data["clips"]) for data in self.sheets.values())

        # Always compute tiles dirs so downstream sheet building can run even if there are no clips.
        sheet_tiles_dirs: Dict[str, Path] = {
            sid: self.get_sheet_tiles_dir(data["path"], sid) for sid, data in self.sheets.items()
        }

        if total_clips_all == 0:
            console.print("[yellow]No clips to process[/yellow]")
            self._last_tile_stats = {
                "total": 0,
                "up_to_date": 0,
                "queued": 0,
                "succeeded": 0,
                "failed": 0,
            }
            return sheet_tiles_dirs

        dirty_jobs: List[tuple] = []
        up_to_date = 0

        for sid, data in self.sheets.items():
            tiles_dir = sheet_tiles_dirs[sid]
            target_res, _grid, duration, fps = self.get_sheet_parameters(sid)

            for c in data["clips"]:
                output_tile_path = tiles_dir / self.get_output_tile_filename(c)
                src_path = Path(c["path"])

                force = False
                if self.regenerate_all:
                    force = True
                elif self._clip_matches_regenerate_list(c):
                    force = True
                elif not output_tile_path.exists():
                    force = True
                elif not self.ignore_changed_tiles:
                    # Default behavior: if the source is newer than the tile, the tile is dirty.
                    # (If source doesn't exist, normalization will fail later anyway.)
                    if self._mtime(src_path) > self._mtime(output_tile_path):
                        force = True

                if force:
                    dirty_jobs.append((c, duration, tiles_dir, target_res, fps, output_tile_path))
                else:
                    up_to_date += 1

        console.print(f"{up_to_date} tiles up to date")

        if self.regenerate_tiles:
            unmatched = self.regenerate_tiles.difference(self._matched_regenerate_tile_keys)
            if unmatched:
                console.print(
                    "[yellow]Warning:[/yellow] --regenerate-tiles names not found in manifest: "
                    + ", ".join(sorted(unmatched))
                )

        if not dirty_jobs:
            console.print("0 tiles to normalize")
            console.print()

            self._last_tile_stats = {
                "total": total_clips_all,
                "up_to_date": up_to_date,
                "queued": 0,
                "succeeded": 0,
                "failed": 0,
            }

            return sheet_tiles_dirs

        console.print(f"{len(dirty_jobs)} tiles to normalize\n")

        # Mark sheets impacted by tile work so we can force dependent sheet rebuild even when mtime checks are disabled.
        self._sheets_with_tile_work = {str(job[0]["sheet_id"]) for job in dirty_jobs}

        display = TileNormalizationDisplay(len(dirty_jobs), console)
        executor = get_global_executor()

        all_futures = {}
        tiles_succeeded = 0
        tiles_failed = 0

        for (clip, duration, tiles_dir, target_res, fps, output_tile_path) in dirty_jobs:
            future = executor.submit(
                self.normalize_clip_to_sheet,
                clip,
                duration,
                tiles_dir,
                target_res,
                fps,
                True,
            )

            future_id = id(future)
            all_futures[future] = clip
            display.start_job(future_id, clip["uid"], clip["sheet_id"], clip["path"], str(output_tile_path))
            display.register_future(future_id, future)

        display.start_display()
        try:
            for future in as_completed(all_futures):
                try:
                    future.result()
                    tiles_succeeded += 1
                except Exception as e:
                    tiles_failed += 1
                    display.print_error(all_futures[future]["uid"], e)
                finally:
                    # Always advance the progress counter so the display completes.
                    display.complete_job(id(future))
        finally:
            display.stop_display()

        console.print(display.print_summary())
        console.print()

        self._last_tile_stats = {
            "total": total_clips_all,
            "up_to_date": up_to_date,
            "queued": len(dirty_jobs),
            "succeeded": tiles_succeeded,
            "failed": tiles_failed,
        }

        return sheet_tiles_dirs

    def _iter_expected_tile_paths(self, sheet_id: str, tiles_dir: Path) -> Iterable[Path]:
        for clip in self.sheets[sheet_id]["clips"]:
            yield tiles_dir / self.get_output_tile_filename(clip)

    def build_all_sheets(self, sheet_tiles_dirs: Dict[str, Path], console: Console) -> None:
        """Build sprite sheets incrementally.

        A sheet is considered dirty if:
          - `regenerate_all` is set
          - the sheet output file does not exist
          - any expected tile does not exist
          - (default) any expected tile is newer than the sheet output (mtime)
          - any tile for that sheet was regenerated/queued in this run

        Set `ignore_changed_tiles=True` to disable the mtime comparison and use existence-only incremental behavior.
        """
        if not self.sheets:
            console.print("[yellow]No sheets to build[/yellow]")
            self._last_sheet_stats = {
                "total": 0,
                "up_to_date": 0,
                "queued": 0,
                "succeeded": 0,
                "failed": 0,
            }
            return

        dirty_sheet_ids: List[str] = []
        up_to_date = 0

        for sid, data in self.sheets.items():
            tiles_dir = sheet_tiles_dirs.get(sid) or self.get_sheet_tiles_dir(data["path"], sid)
            output_path = Path(data["path"])

            if self.regenerate_all or not output_path.exists():
                dirty_sheet_ids.append(sid)
                continue

            sheet_mtime = self._mtime(output_path)
            expected_tiles = list(self._iter_expected_tile_paths(sid, tiles_dir))

            missing_tile = any(not p.exists() for p in expected_tiles)
            if missing_tile:
                dirty_sheet_ids.append(sid)
                continue

            if sid in self._sheets_with_tile_work:
                dirty_sheet_ids.append(sid)
                continue

            if not self.ignore_changed_tiles:
                newest_tile_mtime = max((self._mtime(p) for p in expected_tiles), default=0.0)
                if newest_tile_mtime > sheet_mtime:
                    dirty_sheet_ids.append(sid)
                    continue

            up_to_date += 1

        console.print(f"{up_to_date} sheets up to date")

        if not dirty_sheet_ids:
            console.print("0 sheets to build")
            console.print()
            self._last_sheet_stats = {
                "total": len(self.sheets),
                "up_to_date": up_to_date,
                "queued": 0,
                "succeeded": 0,
                "failed": 0,
            }
            return

        console.print(f"{len(dirty_sheet_ids)} sheets to build\n")

        if self.sequential:
            sheets_succeeded, sheets_failed = self._build_sheets_sequential(dirty_sheet_ids, sheet_tiles_dirs, console)
        else:
            sheets_succeeded, sheets_failed = self._build_sheets_parallel(dirty_sheet_ids, sheet_tiles_dirs, console)

        self._last_sheet_stats = {
            "total": len(self.sheets),
            "up_to_date": up_to_date,
            "queued": len(dirty_sheet_ids),
            "succeeded": sheets_succeeded,
            "failed": sheets_failed,
        }

    def _build_sheets_sequential(self, sheet_ids: List[str], sheet_tiles_dirs: Dict[str, Path], console: Console) -> Tuple[int, int]:
        """Build all sprite sheets sequentially.

        Args:
            sheet_tiles_dirs: Dictionary mapping sheet IDs to their tiles directories.
            console: Console instance for output.
        """
        display = SpriteSheetDisplay(len(sheet_ids), console)
        display.start_display()

        sheets_succeeded = 0
        sheets_failed = 0

        try:
            for sid in sheet_ids:
                data = self.sheets[sid]
                tiles_dir = sheet_tiles_dirs[sid]
                num_tiles = len(data["clips"])

                # Get sheet parameters
                tile_resolution, grid, duration, fps = self.get_sheet_parameters(sid)

                # Calculate resulting sprite sheet resolution
                sheet_w, sheet_h = data["resolution"]

                future_id = id(sid)
                display.start_job(future_id, sid, data["path"], num_tiles, tile_resolution, (sheet_w, sheet_h), fps)

                try:
                    self.build_sheet(
                        sid,
                        tiles_dir,
                        tile_resolution,
                        grid,
                        duration,
                        fps
                    )
                    sheets_succeeded += 1
                except Exception as e:
                    sheets_failed += 1
                    display.print_error(f"Sheet {sid}", e)
                finally:
                    # Always advance the progress counter so the display completes.
                    display.complete_job(future_id)
        finally:
            display.stop_display()

        console.print()
        return sheets_succeeded, sheets_failed

    def _build_sheets_parallel(self, sheet_ids: List[str], sheet_tiles_dirs: Dict[str, Path], console: Console) -> Tuple[int, int]:
        """Build all sprite sheets in parallel.

        Args:
            sheet_tiles_dirs: Dictionary mapping sheet IDs to their tiles directories.
            console: Console instance for output.
        """
        # Create display for sheet generation
        display = SpriteSheetDisplay(len(sheet_ids), console)

        # Get global executor (reuse the same one)
        executor = get_global_executor()

        # Collect all futures
        all_futures = {}

        # Submit all sheet building jobs
        for sid in sheet_ids:
            data = self.sheets[sid]
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
                duration,
                fps
            )

            future_id = id(future)
            all_futures[future] = sid
            display.start_job(future_id, sid, data["path"], num_tiles, tile_resolution, (sheet_w, sheet_h), fps)
            display.register_future(future_id, future)

        console.print(f"Building {len(sheet_ids)} sprite sheets...\n")

        # Use Live display for progress tracking
        display.start_display()

        sheets_succeeded = 0
        sheets_failed = 0

        try:
            for future in as_completed(all_futures):
                try:
                    future.result()
                    sheets_succeeded += 1
                except Exception as e:
                    sheets_failed += 1
                    display.print_error(f"Sheet {all_futures[future]}", e)
                finally:
                    # Always advance the progress counter so the display completes.
                    display.complete_job(id(future))
        finally:
            display.stop_display()

        # Print summary
        console.print(display.print_summary())
        console.print()

        return sheets_succeeded, sheets_failed

    def run(self):
        """Run the complete sheet building pipeline: parse, normalize tiles, build sheets."""
        self.parse_manifest()
        console = Console()

        try:
            # Step 1: Normalize tiles (incremental)
            sheet_tiles_dirs = self.normalize_all_tiles(console)

            # Step 2: Build sheets (incremental)
            self.build_all_sheets(sheet_tiles_dirs, console)

            # Job summary
            tile = self._last_tile_stats
            sheet = self._last_sheet_stats

            console.print("[bold]Job Summary[/bold]")
            console.print(
                f"Tiles: {tile.get('succeeded', 0)} regenerated, {tile.get('up_to_date', 0)} up to date, {tile.get('failed', 0)} failed"
            )
            console.print(
                f"Sheets: {sheet.get('succeeded', 0)} built, {sheet.get('up_to_date', 0)} up to date, {sheet.get('failed', 0)} failed"
            )
            console.print()

        finally:
            # Ensure executor is cleanly shutdown when all sheets are done
            shutdown_global_executor()

if __name__ == "__main__":
    raise RuntimeError("SheetBuilder must be called through rhino_eyes_manager CLI via the build-sheets command")
