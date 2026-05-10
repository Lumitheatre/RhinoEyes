@tool
extends Node
class_name Cue

## Transition duration in seconds when going to this cue. 0 = instant snap.
@export_range(0.0, 30.0, 0.05) var transition_time: float = 1.0

## One or more (entity_ids → state) pairs that make up this cue.
## Entities sharing an identical state can be listed together in one CueEntry.
@export var entries: Array[CueEntry] = []

@export_tool_button("Preview Cue States", "ImportCheck")
var _preview_btn: Callable = preview_cue_states

@export_tool_button("Replace Cue State with Editor State", "Reload")
var _update_btn: Callable = update_cue_states

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

func update_cue_states() -> void:
	if not Engine.is_editor_hint():
		push_warning("Cue: update_cue_states only works in the editor.")
		return

	# Get the CueManager parent
	var manager = get_parent()
	if not manager is CueManager:
		push_warning("Cue: Parent is not a CueManager. Cannot update cue states.")
		return

	# Capture the current state of all entities
	var new_entries = manager.capture_entity_states()

	if new_entries.is_empty():
		push_warning("Cue: No CueEntity nodes found. Cannot update cue states.")
		return

	# Update this cue's entries with the newly captured states
	entries = new_entries

	print("Cue: Updated '%s' with %d entr%s." % [
		name, entries.size(), "ies" if entries.size() != 1 else "y"
	])
