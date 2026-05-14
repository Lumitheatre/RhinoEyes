extends EntityState
class_name EyeActorCueState

## Per-cue state for an EyeActor (changes from cue to cue).
@export var track_target: bool = true
@export_range(1, 3) var aggravation: int = 1
@export_range(0.0, 1.0, 0.01) var opacity_multiplier: float = 1.0
