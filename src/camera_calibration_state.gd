extends EntityState
class_name CameraCalibrationState

## Calibration state for a Camera3D (position, rotation, size).
## Stored as local transform components.
@export var position: Vector3 = Vector3.ZERO
@export var rotation_degrees: Vector3 = Vector3.ZERO
@export var size: float = 1.0
