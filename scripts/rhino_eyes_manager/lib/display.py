"""Display utilities for progress tracking and logging."""

import time
import threading
from typing import Dict, Any, Optional
from pathlib import Path

from rich.console import Console  # type: ignore
from rich.live import Live  # type: ignore


class BaseProgressDisplay:
    """Base class for progress displays with common functionality."""

    def __init__(self, total_items: int, console: Console | None = None, phase_name: str = "Processing"):
        """Initialize the display.

        Args:
            total_items: Total number of items to process.
            console: Optional Console instance for output.
            phase_name: Name of the processing phase (e.g., "Tile Normalization", "Sheet Generation").
        """
        self.total_items = total_items
        self.console = console or Console()
        self.phase_name = phase_name
        self.completed = 0
        self.in_progress: Dict[int, Dict[str, Any]] = {}  # Maps future id to item info
        self.start_times: Dict[int, float] = {}  # Maps future id to start time
        self.futures: Dict[int, Any] = {}  # Maps future id to future object for running status check
        self.live_display: Optional[Any] = None
        self.phase_start_time = time.time()
        self._update_thread = None
        self._stop_update = False

    def register_future(self, future_id: int, future) -> None:
        """Register a future object for running status tracking.

        Args:
            future_id: Unique ID for the future object.
            future: The future object to track.
        """
        self.futures[future_id] = future

    def complete_job(self, future_id: int) -> None:
        """Record job completion.

        Args:
            future_id: Unique ID for the future object.
        """
        self.completed += 1
        if future_id in self.in_progress:
            del self.in_progress[future_id]
        if future_id in self.start_times:
            del self.start_times[future_id]

    def _format_time(self, seconds: float) -> str:
        """Format seconds into human-readable duration.

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted time string.
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m{secs}s"

    def _calculate_eta(self) -> str:
        """Calculate ETA based on current progress.

        Returns:
            Formatted ETA string or "calculating..." if insufficient data.
        """
        if self.completed == 0:
            return "calculating..."

        elapsed = time.time() - self.phase_start_time
        avg_time_per_item = elapsed / self.completed
        remaining_items = self.total_items - self.completed
        eta_seconds = avg_time_per_item * remaining_items

        return self._format_time(eta_seconds)

    def generate_progress_display(self) -> str:
        """Generate progress display with live job details and totals.

        Must be implemented by subclasses.

        Returns:
            String with formatted progress information (with rich markup).
        """
        raise NotImplementedError("Subclasses must implement generate_progress_display")

    def _update_loop(self) -> None:
        """Background thread that updates display on a timer."""
        while not self._stop_update:
            if self.live_display:
                self.live_display.update(self.generate_progress_display())
            time.sleep(0.5)  # Update every 500ms for responsiveness

    def start_display(self) -> None:
        """Start the live display with background updates."""
        self.live_display = Live(
            self.generate_progress_display(),
            refresh_per_second=2,
            console=self.console,
            transient=False
        )
        if self.live_display is not None:
            self.live_display.__enter__()  # type: ignore
            # Start background update thread
            self._stop_update = False
            self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self._update_thread.start()

    def stop_display(self) -> None:
        """Stop the live display and background thread."""
        # Stop the update thread
        self._stop_update = True
        if self._update_thread is not None:
            self._update_thread.join(timeout=1.0)
            self._update_thread = None

        if self.live_display is not None:
            # Update one final time with empty content to clear the display
            try:
                self.live_display.update("")
            except Exception:
                pass
            self.live_display.__exit__(None, None, None)  # type: ignore
            self.live_display = None

    def print_error(self, item_id: str, error: Exception) -> None:
        """Print error message.

        Args:
            item_id: The item ID.
            error: The exception that occurred.
        """
        self.console.print(f"[red]Error processing {item_id}: {error}[/red]")
        self.console.print_exception()


class TileNormalizationDisplay(BaseProgressDisplay):
    """Manages the display of sprite tile normalization progress."""

    def __init__(self, total_clips: int, console: Console | None = None):
        """Initialize the display.

        Args:
            total_clips: Total number of clips to process.
            console: Optional Console instance for output.
        """
        super().__init__(total_clips, console, "Sprite Tile Normalization")

    def start_job(self, future_id: int, clip_uid: str, sheet_id: str, source_path: str, output_tile_path: Optional[str] = None,
                  source_resolution: Optional[tuple] = None, target_resolution: Optional[tuple] = None,
                  loop_count: Optional[int] = None, speed_factor: Optional[float] = None) -> None:
        """Record the start of a job (when submitted, not when actually running).

        Args:
            future_id: Unique ID for the future object.
            clip_uid: The clip UID.
            sheet_id: The sheet ID.
            source_path: Path to the source clip file.
            output_tile_path: Path to the output tile file being generated.
            source_resolution: Tuple of (width, height) for source video.
            target_resolution: Tuple of (width, height) for target tile.
            loop_count: Number of loops for the clip.
            speed_factor: Speed adjustment factor.
        """
        self.in_progress[future_id] = {
            "uid": clip_uid,
            "sheet_id": sheet_id,
            "source": Path(source_path).name,
            "output_tile": Path(output_tile_path).name if output_tile_path else "unknown",
            "actual_start_recorded": False,  # Track when actual execution begins
            "source_res": source_resolution,
            "target_res": target_resolution,
            "loop_count": loop_count,
            "speed_factor": speed_factor
        }
        # Don't set start_times here - wait until future actually starts running

    def generate_progress_display(self) -> str:
        """Generate progress display with live job details and totals.

        Returns:
            String with formatted progress information (with rich markup).
        """
        lines = []
        current_time = time.time()

        # Calculate max widths for alignment
        max_uid_width = max(
            (len(str(info['uid'])) for info in self.in_progress.values()),
            default=3
        )
        max_sheet_width = max(
            (len(str(info['sheet_id'])) for info in self.in_progress.values()),
            default=5
        )
        max_source_width = max(
            (len(info['source']) for info in self.in_progress.values()),
            default=20
        )

        # Calculate max widths for tile output
        max_output_width = max(
            (len(info['output_tile']) for info in self.in_progress.values()),
            default=15
        )

        # Display each in-progress job (only if future is actually running)
        for future_id, clip_info in self.in_progress.items():
            # Check if the future is still running
            future = self.futures.get(future_id)
            if future is not None and not future.running():
                continue

            # Record the actual start time when we first notice the future is running
            if not clip_info["actual_start_recorded"]:
                self.start_times[future_id] = time.time()
                clip_info["actual_start_recorded"] = True

            elapsed = current_time - self.start_times.get(future_id, current_time)
            elapsed_str = self._format_time(elapsed)

            # Pad fields for alignment
            uid_padded = str(clip_info['uid']).ljust(max_uid_width)
            sheet_padded = str(clip_info['sheet_id']).ljust(max_sheet_width)
            source_padded = clip_info['source'].ljust(max_source_width)
            output_padded = clip_info['output_tile'].ljust(max_output_width)

            # Format: "• Clip UID | Sheet ID | Source | Output Tile | 12s"
            line = (
                f"• Clip {uid_padded} | "
                f"Sheet {sheet_padded} | "
                f"{source_padded} -> "
                f"{output_padded} | "
                f"{elapsed_str}"
            )
            lines.append(line)

        # Progress summary line with markup
        eta = self._calculate_eta()
        elapsed_total = self._format_time(time.time() - self.phase_start_time)
        progress_pct = (self.completed / self.total_items * 100) if self.total_items > 0 else 0

        summary = (
            f"\n[bold magenta]{self.phase_name}:[/bold magenta] "
            f"{self.completed}/{self.total_items} ({progress_pct:.0f}%) | "
            f"Elapsed: {elapsed_total} | "
            f"ETA: {eta}"
        )
        lines.append(summary)

        return "\n".join(lines)

    def print_summary(self) -> str:
        """Generate and return the summary line only.

        Returns:
            Summary string with progress information.
        """
        eta = self._calculate_eta()
        elapsed_total = self._format_time(time.time() - self.phase_start_time)
        progress_pct = (self.completed / self.total_items * 100) if self.total_items > 0 else 0

        return (
            f"[bold magenta]{self.phase_name}:[/bold magenta] "
            f"{self.completed}/{self.total_items} ({progress_pct:.0f}%) | "
            f"Elapsed: {elapsed_total}"
        )


class SpriteSheetDisplay(BaseProgressDisplay):
    """Manages the display of sprite sheet generation progress."""

    def __init__(self, total_sheets: int, console: Console | None = None):
        """Initialize the display.

        Args:
            total_sheets: Total number of sheets to generate.
            console: Optional Console instance for output.
        """
        super().__init__(total_sheets, console, "Sprite Sheet Generation")
        # Track channel grid sub-jobs for each sheet
        self.channel_jobs: Dict[int, Dict[str, Any]] = {}  # Maps future_id to channel info
        self.channel_start_times: Dict[int, float] = {}  # Maps channel future_id to start time
        self.channel_futures: Dict[int, Any] = {}  # Maps channel future_id to future object

    def start_job(self, future_id: int, sheet_id: str, output_path: str, num_tiles: int,
                  tile_resolution=None, sheet_resolution=None, fps=30):
        """Record the start of a sheet generation job.

        Args:
            future_id: Unique ID for the future object.
            sheet_id: The sheet ID.
            output_path: Path to the output sheet file.
            num_tiles: Number of tiles in this sheet.
            tile_resolution: Tuple of (width, height) for individual tiles.
            sheet_resolution: Tuple of (width, height) for the final sprite sheet.
            fps: Frames per second for the output sheet.
        """
        self.in_progress[future_id] = {
            "sheet_id": sheet_id,
            "output": Path(output_path).name,
            "num_tiles": num_tiles,
            "tile_resolution": tile_resolution,
            "sheet_resolution": sheet_resolution,
            "fps": fps,
            "actual_start_recorded": False
        }

    def start_channel_job(self, future_id, sheet_id, channel, intermediate_path):
        """Record the start of a channel grid generation sub-job.

        Args:
            future_id: Unique ID for the channel future object.
            sheet_id: The parent sheet ID.
            channel: Channel identifier ('R', 'G', or 'B').
            intermediate_path: Path to the intermediate channel file.
        """
        self.channel_jobs[future_id] = {
            "sheet_id": sheet_id,
            "channel": channel,
            "full_path": Path(intermediate_path),
            "actual_start_recorded": False
        }

    def register_channel_future(self, future_id, future):
        """Register a channel future object for running status tracking.

        Args:
            future_id: Unique ID for the channel future object.
            future: The future object to track.
        """
        self.channel_futures[future_id] = future

    def complete_channel_job(self, future_id):
        """Record channel job completion.

        Args:
            future_id: Unique ID for the channel future object.
        """
        if future_id in self.channel_jobs:
            del self.channel_jobs[future_id]
        if future_id in self.channel_start_times:
            del self.channel_start_times[future_id]

    def generate_progress_display(self) -> str:
        """Generate progress display with live job details and totals.

        Returns:
            String with formatted progress information (with rich markup).
        """
        lines = []
        current_time = time.time()

        # Calculate max widths for alignment
        max_sheet_width = max(
            (len(str(info['sheet_id'])) for info in self.in_progress.values()),
            default=5
        )
        max_output_width = max(
            (len(info['output']) for info in self.in_progress.values()),
            default=20
        )

        # Display each in-progress job (only if future is actually running)
        for future_id, sheet_info in self.in_progress.items():
            # Check if the future is still running
            future = self.futures.get(future_id)
            if future is not None and not future.running():
                continue

            # Record the actual start time when we first notice the future is running
            if not sheet_info["actual_start_recorded"]:
                self.start_times[future_id] = time.time()
                sheet_info["actual_start_recorded"] = True

            elapsed = current_time - self.start_times.get(future_id, current_time)
            elapsed_str = self._format_time(elapsed)

            # Pad fields for alignment
            sheet_padded = str(sheet_info['sheet_id']).ljust(max_sheet_width)
            output_padded = sheet_info['output'].ljust(max_output_width)

            # Format tile and sheet resolutions
            # Use '×' instead of 'x' to prevent Rich from highlighting it as a hex number
            tile_res = f"{sheet_info['tile_resolution'][0]}×{sheet_info['tile_resolution'][1]}" if sheet_info['tile_resolution'] else "?"
            sheet_res = f"{sheet_info['sheet_resolution'][0]}×{sheet_info['sheet_resolution'][1]}" if sheet_info['sheet_resolution'] else "?"
            fps = sheet_info.get('fps', 30)

            # Format: "• Sheet ID | output.mp4 | 3840×2160 @ 30fps (tile: 420×270) | 64 tiles | 12s"
            line = (
                f"• Sheet {sheet_padded} | "
                f"{output_padded} | "
                f"{sheet_res} @ {fps}fps (tile: {tile_res}) | "
                f"{sheet_info['num_tiles']} tiles | "
                f"{elapsed_str}"
            )
            lines.append(line)

            # Show channel grid sub-jobs for this sheet (indented)
            sheet_id = sheet_info['sheet_id']
            for i, (ch_future_id, ch_info) in enumerate(self.channel_jobs.items()):
                if ch_info['sheet_id'] != sheet_id:
                    continue

                # Check if the channel future is actually running
                ch_future = self.channel_futures.get(ch_future_id)
                if ch_future is not None and not ch_future.running():
                    continue

                # Record the actual start time when we first notice the future is running
                if not ch_info["actual_start_recorded"]:
                    self.channel_start_times[ch_future_id] = time.time()
                    ch_info["actual_start_recorded"] = True

                ch_elapsed = current_time - self.channel_start_times.get(ch_future_id, current_time)
                ch_elapsed_str = self._format_time(ch_elapsed)

                is_last = i == len(self.channel_jobs) - 1
                tree_char = "└─" if is_last else "├─"

                # Format channel sub-job with tree character
                # Calculate relative path: sheet_tiles/_intermediates/channel_R.mp4
                # The intermediate path structure is: path/to/sheet_tiles/_intermediates/channel_R.mp4
                # We want to show everything after the sheet's parent directory
                full_path = ch_info['full_path']
                # Get the path relative to the sheet's parent by taking the last 3 parts
                # (sheet_tiles / _intermediates / channel_X.mp4)
                relative_parts = full_path.parts[-3:]
                relative_path = str(Path(*relative_parts))
                
                ch_line = (
                    f"  {tree_char} Channel {ch_info['channel']} -> {relative_path} | "
                    f"{ch_elapsed_str}"
                )
                lines.append(ch_line)

        # Progress summary line with markup
        eta = self._calculate_eta()
        elapsed_total = self._format_time(time.time() - self.phase_start_time)
        progress_pct = (self.completed / self.total_items * 100) if self.total_items > 0 else 0

        summary = (
            f"\n[bold cyan]{self.phase_name}:[/bold cyan] "
            f"{self.completed}/{self.total_items} ({progress_pct:.0f}%) | "
            f"Elapsed: {elapsed_total} | "
            f"ETA: {eta}"
        )
        lines.append(summary)

        return "\n".join(lines)

    def print_summary(self) -> str:
        """Generate and return the summary line only.

        Returns:
            Summary string with progress information.
        """
        eta = self._calculate_eta()
        elapsed_total = self._format_time(time.time() - self.phase_start_time)
        progress_pct = (self.completed / self.total_items * 100) if self.total_items > 0 else 0

        return (
            f"[bold cyan]{self.phase_name}:[/bold cyan] "
            f"{self.completed}/{self.total_items} ({progress_pct:.0f}%) | "
            f"Elapsed: {elapsed_total}"
        )
