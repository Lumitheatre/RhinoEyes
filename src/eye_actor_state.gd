extends EntityState
class_name EyeActorState

@export var track_target: bool = true
@export_range(1, 3) var aggravation: int = 1
@export_range(0.0, 1.0, 0.01) var opacity_multiplier: float = 1.0
