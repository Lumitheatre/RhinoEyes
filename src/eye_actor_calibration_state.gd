extends EntityState
class_name EyeActorCalibrationState

## Global calibration state for an EyeActor (does not change from cue to cue).
## Stored as local transform components.
@export var position: Vector3 = Vector3.ZERO
@export var rotation_degrees: Vector3 = Vector3.ZERO
@export var scale: Vector3 = Vector3.ONE
