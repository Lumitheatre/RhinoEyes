@tool
extends Node
class_name CueManager

## Root node to search for CueEntity implementors.
## If unset, the full scene tree is searched from the root.
@export var entity_root: Node

## Enable looping playback. When true, going past the last cue wraps to index 0.
@export var loop_playback: bool = true

## Starting index when looping. When looping wraps around, it goes to this index.
@export var loop_start_index: int = 0

var _current_index: int = -1

signal cue_changed(index: int, cue: Cue)

func _ready() -> void:
    if Engine.is_editor_hint():
        return
    if get_cue_count() > 0:
        go_to_immediately(0)

func _input(event: InputEvent) -> void:
    if event.is_action_pressed("cue_next"):
        go_next()
        get_tree().root.set_input_as_handled()
    elif event.is_action_pressed("cue_prev"):
        go_previous()
        get_tree().root.set_input_as_handled()

# --- Cue list access ---

func get_cues() -> Array[Cue]:
    var result: Array[Cue] = []
    for child in get_children():
        if child is Cue:
            result.append(child)
    return result

func get_cue_count() -> int:
    return get_cues().size()

func get_current_index() -> int:
    return _current_index

# --- Cue progression ---

func go_to(index: int, transition_override: float = -1.0) -> void:
    var cues := get_cues()
    if cues.is_empty():
        push_warning("CueManager: No Cue children found.")
        return

    # Handle looping
    if loop_playback:
        var cue_count := cues.size()
        var loop_end_index := cue_count - 1

        # Wrap around if we go past the last index
        if index > loop_end_index:
            index = loop_start_index
        elif index < loop_start_index:
            index = loop_end_index
    else:
        index = clamp(index, 0, cues.size() - 1)

    _current_index = index
    var cue: Cue = cues[index]
    _apply_cue(cue, transition_override)
    cue_changed.emit(_current_index, cue)

func go_to_immediately(index: int) -> void:
    go_to(index, 0.0)

func go_next() -> void:
    go_to(_current_index + 1)

func go_previous() -> void:
    go_to(_current_index - 1)

# --- Application ---

func _apply_cue(cue: Cue, transition_override: float = -1.0) -> void:
    var entity_map := _build_entity_map()
    # Use override if provided (>= 0), otherwise use cue's transition time
    var transition_time := cue.transition_time if transition_override < 0.0 else transition_override
    for entry: CueEntry in cue.entries:
        if not entry or not entry.state:
            continue
        for entity_id: String in entry.entity_ids:
            if entity_map.has(entity_id):
                var entity: Node = entity_map[entity_id]
                if entity.has_method("transition_to"):
                    entity.transition_to(entry.state, transition_time)

## Preview a cue's states on all entities in the scene (for editor preview)
func preview_cue_state(cue: Cue) -> void:
    if not Engine.is_editor_hint():
        push_warning("CueManager: preview_cue_state only works in the editor.")
        return

    var entity_map := _build_entity_map()

    # Apply each entry's state to its entities with instant transition
    for entry: CueEntry in cue.entries:
        if not entry or not entry.state:
            continue
        for entity_id: String in entry.entity_ids:
            if entity_map.has(entity_id):
                var entity: Node = entity_map[entity_id]
                if entity.has_method("transition_to"):
                    # Use 0 transition time for instant preview in editor
                    entity.transition_to(entry.state, 0.0)

func _build_entity_map() -> Dictionary:
    var root: Node = entity_root if entity_root else get_tree().root
    var map: Dictionary = {}
    _collect_entities(root, map)
    return map

func _collect_entities(node: Node, map: Dictionary) -> void:
    if node.has_method("get_entity_id") and node.has_method("transition_to"):
        map[node.get_entity_id()] = node
    for child in node.get_children():
        _collect_entities(child, map)

# --- Editor helper ---

## Captures the current state of every selected EyeActor and appends a new Cue child.
## Select one or more EyeActor nodes in the editor before pressing this button.
@export_tool_button("Capture Selected EyeActors as Cue", "Add")
var _capture_btn: Callable = capture_current_state_as_cue

func get_nodes() -> Array[Node]:
    var nodes: Array[Node] = []
    var stack: Array[Node] = [get_tree().edited_scene_root]
    while not stack.is_empty():
        var current = stack.pop_back()
        nodes.append(current)
        stack.append_array(current.get_children())
    return nodes

func capture_current_state_as_cue() -> void:
    if not Engine.is_editor_hint():
        push_warning("CueManager: capture_current_state_as_cue only works in the editor.")
        return

    var entries := capture_entity_states()

    if entries.is_empty():
        push_warning("CueManager: No CueEntity nodes selected. Select one or more EyeActor nodes first.")
        return

    var cue := Cue.new()
    cue.name = "Cue%d" % (get_cue_count() + 1)
    cue.entries = entries

    add_child(cue, true)
    cue.owner = get_tree().edited_scene_root

    print("CueManager: Added '%s' with %d entr%s." % [
        cue.name, entries.size(), "ies" if entries.size() != 1 else "y"
    ])

## Capture the current state of all entities in the given nodes array
## Returns an array of CueEntry with captured states
func capture_entity_states() -> Array[CueEntry]:
    var nodes: Array[Node] = get_nodes()
    var entries: Array[CueEntry] = []
    for node in nodes:
        if not node.has_method("get_entity_id") or not node.has_method("capture_state"):
            continue
        var entry := CueEntry.new()
        var id_array: Array[String] = []
        id_array.append(node.get_entity_id())
        entry.entity_ids = id_array
        entry.state = node.capture_state()
        entries.append(entry)
    return entries
