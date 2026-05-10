@tool
extends Node
class_name Cue

## Transition duration in seconds when going to this cue. 0 = instant snap.
@export_range(0.0, 30.0, 0.05) var transition_time: float = 1.0

## One or more (entity_ids → state) pairs that make up this cue.
## Entities sharing an identical state can be listed together in one CueEntry.
@export var entries: Array[CueEntry] = []

@export_tool_button("Set Cue State in Editor", "ImportCheck")
var _preview_btn: Callable = preview_cue_states

func preview_cue_states() -> void:
	if not Engine.is_editor_hint():
		push_warning("Cue: preview_cue_states only works in the editor.")
		return

	# Get the CueManager parent
	var manager = get_parent()
	if not manager is CueManager:
		push_warning("Cue: Parent is not a CueManager. Cannot preview cue states.")
		return

	# Call the manager's preview function
	manager.preview_cue_state(self)
