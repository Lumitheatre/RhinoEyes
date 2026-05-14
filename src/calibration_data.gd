@tool
extends Resource
class_name CalibrationData

## Calibration entries mapping entity IDs to EyeActorCalibrationState.
## Each entry is expected to have exactly one entity_id.
@export var entries: Array[CueEntry] = []
