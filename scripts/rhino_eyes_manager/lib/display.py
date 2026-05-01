"""Display utilities for progress tracking and logging."""

import time
import threading
from typing import Dict, Any, Optional
from pathlib import Path

from rich.console import Console  # type: ignore
from rich.live import Live  # type: ignore


class TileNormalizationDisplay:
    """Manages the display of sprite tile normalization progress."""
    
    def __init__(self, total_clips: int, console: Console | None = None):
        """Initialize the display.
        
        Args:
            total_clips: Total number of clips to process.
            console: Optional Console instance for output.
        """
        self.total_clips = total_clips
        self.console = console or Console()
        self.completed = 0
        self.in_progress: Dict[int, Dict[str, Any]] = {}  # Maps future id to clip info
        self.start_times: Dict[int, float] = {}  # Maps future id to start time
        self.futures: Dict[int, Any] = {}  # Maps future id to future object for running status check
        self.live_display: Optional[Any] = None
        self.phase_start_time = time.time()
        self._update_thread = None
        self._stop_update = False
    
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
        avg_time_per_clip = elapsed / self.completed
        remaining_clips = self.total_clips - self.completed
        eta_seconds = avg_time_per_clip * remaining_clips
        
        return self._format_time(eta_seconds)
    
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
                f"{source_padded} | "
                f"{output_padded} | "
                f"{elapsed_str}"
            )
            lines.append(line)
        
        # Progress summary line with markup
        eta = self._calculate_eta()
        elapsed_total = self._format_time(time.time() - self.phase_start_time)
        progress_pct = (self.completed / self.total_clips * 100) if self.total_clips > 0 else 0
        
        summary = (
            f"\n[bold magenta]Sprite Tile Normalization:[/bold magenta] "
            f"{self.completed}/{self.total_clips} ({progress_pct:.0f}%) | "
            f"Elapsed: {elapsed_total} | "
            f"ETA: {eta}"
        )
        lines.append(summary)
        
        return "\n".join(lines)
    
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
            refresh_per_second=4,
            console=self.console
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
            self.live_display.__exit__(None, None, None)  # type: ignore
            self.live_display = None
    
    def clear_job_lines(self) -> None:
        """Clear all job status lines, leaving only summary line visible."""
        # Clear the in-progress and start_times dicts
        self.in_progress.clear()
        self.start_times.clear()
        
        # Update display with just the summary line
        if self.live_display:
            self.live_display.update(self.generate_progress_display())
    
    def print_completion(self, sheet_id: str) -> None:
        """Print completion message.
        
        Args:
            sheet_id: The sheet ID.
        """
        total_time = self._format_time(time.time() - self.phase_start_time)
        self.console.print(
            f"[bold green]✓ Completed {self.total_clips} tiles for Sheet {sheet_id} in {total_time}[/bold green]"
        )
    
    def print_error(self, clip_uid: str, error: Exception) -> None:
        """Print error message.
        
        Args:
            clip_uid: The clip UID.
            error: The exception that occurred.
        """
        self.console.print(f"[red]Error processing clip {clip_uid}: {error}[/red]")
