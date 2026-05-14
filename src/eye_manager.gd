@tool
extends Node
class_name EyeManager

static var instance: EyeManager

func _enter_tree():
    instance = self

func _exit_tree():
    if instance == self:
        instance = null

## The eye manifest resource that contains all character and sprite sheet data
## Assign your eye_manifest.v2.tres (or similar) resource here in the Inspector
@export var manifest: EyeManifest:
    set(val):
        manifest = val

@export_group("Target Tracking")

## This is the target the transform of which the eyes follow
@export var target_node: EyeTarget

@export_group("Calibration")

## Path to the CalibrationData .tres resource to load on startup and save to.
@export_file("*.tres") var calibration_data_path: String = "res://src/calibration_data.tres"

## UI Camera to include in calibration (optional)
@export var ui_camera: Camera3D

## Projection Camera to include in calibration (optional)
@export var projection_camera: Camera3D

## Save calibration state from the current EyeActor transforms into calibration_data_path.
@export_tool_button("Save Calibration State", "Save")
var _save_calibration_btn: Callable = save_calibration_state

## Load calibration state from the current EyeActor transforms into calibration_data_path.
@export_tool_button("Load Calibration State to Editor", "ConfirmImport")
var _load_calibration_btn: Callable = _load_and_apply_calibration

func _get_configuration_warnings() -> PackedStringArray:
    var warnings = PackedStringArray()
    if not manifest:
        warnings.append("EyeManager: No manifest assigned. Assign your eye_manifest resource in the Inspector.")
    return warnings

# Keyed by file path: { "path": { "player": VideoStreamPlayer, "users": int } }
var video_pool: Dictionary = {}
var _video_container: Node = null

func _ready():
    if not manifest:
        push_error("EyeManager: Manifest not assigned! Please assign eye_manifest.v2.tres in the Inspector.")

    # Create a hidden container for video players so they don't appear in the viewport
    _video_container = Control.new()
    _video_container.name = "_VideoPool_Hidden"
    add_child(_video_container)
    _video_container.hide()

    if not Engine.is_editor_hint():
        # Load and apply calibration at runtime startup.
        call_deferred("_load_and_apply_calibration")

func _input(event: InputEvent) -> void:
    if Engine.is_editor_hint():
        return
    if event.is_action_pressed("save_calibration_state"):
        save_calibration_state()
        get_tree().root.set_input_as_handled()

func get_target_position() -> Vector3:
    if target_node:
        return target_node.global_position
    return Vector3.ZERO

# --- Calibration ---

func _get_eye_actors() -> Array[EyeActor]:
    var result: Array[EyeActor] = []
    _collect_eye_actors(self, result)
    return result

func _collect_eye_actors(node: Node, out: Array[EyeActor]) -> void:
    for child in node.get_children():
        if child is EyeActor:
            out.append(child)
        _collect_eye_actors(child, out)

func _get_calibration_cameras() -> Dictionary:
    """Returns a dictionary of camera identifiers to Camera3D nodes."""
    var cameras: Dictionary = {}
    if ui_camera:
        cameras["ui_camera"] = ui_camera
    if projection_camera:
        cameras["projection_camera"] = projection_camera
    return cameras

func _capture_camera_state(camera: Camera3D) -> CameraCalibrationState:
    """Captures the current calibration state of a camera."""
    var state := CameraCalibrationState.new()
    state.position = camera.position
    state.rotation_degrees = camera.rotation_degrees
    state.size = camera.size
    return state

func _apply_camera_state(camera: Camera3D, state: CameraCalibrationState) -> void:
    """Applies a calibration state to a camera."""
    camera.position = state.position
    camera.rotation_degrees = state.rotation_degrees
    camera.size = state.size

func save_calibration_state() -> void:
    if calibration_data_path.strip_edges() == "":
        push_warning("EyeManager: calibration_data_path is empty; cannot save calibration.")
        return

    var actors := _get_eye_actors()
    var cameras := _get_calibration_cameras()

    if actors.is_empty() and cameras.is_empty():
        push_warning("EyeManager: No EyeActor children or cameras found; nothing to save.")
        return

    var data := CalibrationData.new()
    var entries: Array[CueEntry] = []

    # Save EyeActor calibration states
    for actor: EyeActor in actors:
        var entry := CueEntry.new()
        var ids: Array[String] = []
        ids.append(actor.get_entity_id())
        entry.entity_ids = ids
        entry.state = actor.capture_calibration_state()
        entries.append(entry)

    # Save Camera calibration states
    for camera_path in cameras.keys():
        var camera: Camera3D = cameras[camera_path]
        if camera:
            var entry := CueEntry.new()
            var ids: Array[String] = []
            ids.append(camera_path)
            entry.entity_ids = ids
            entry.state = _capture_camera_state(camera)
            entries.append(entry)

    data.entries = entries

    var err := ResourceSaver.save(data, calibration_data_path)
    if err != OK:
        push_error("EyeManager: Failed to save CalibrationData to '%s' (err=%s)." % [calibration_data_path, err])
        return

    print("EyeManager: Saved calibration for %d EyeActors and %d cameras to %s" % [actors.size(), cameras.size(), calibration_data_path])

func _load_and_apply_calibration() -> void:
    var path := calibration_data_path.strip_edges()
    if path == "":
        return

    if not ResourceLoader.exists(path):
        push_warning("EyeManager: CalibrationData not found at '%s' (skipping)." % path)
        return

    var res = load(path)
    if not res or not (res is CalibrationData):
        push_warning("EyeManager: Resource at '%s' is not CalibrationData (skipping)." % path)
        return

    apply_calibration_data(res as CalibrationData)

func apply_calibration_data(data: CalibrationData) -> void:
    var actors := _get_eye_actors()
    var cameras := _get_calibration_cameras()

    if actors.is_empty() and cameras.is_empty():
        return

    var actor_by_id: Dictionary = {}
    for actor: EyeActor in actors:
        actor_by_id[actor.get_entity_id()] = actor

    var applied_count := 0

    for entry: CueEntry in data.entries:
        if not entry or not entry.state:
            continue

        # Handle EyeActor calibration states
        if entry.state is EyeActorCalibrationState:
            for entity_id: String in entry.entity_ids:
                if actor_by_id.has(entity_id):
                    var actor: EyeActor = actor_by_id[entity_id]
                    actor.transition_to(entry.state, 0.0)
                    applied_count += 1

        # Handle Camera calibration states
        elif entry.state is CameraCalibrationState:
            for entity_id: String in entry.entity_ids:
                if cameras.has(entity_id):
                    var camera: Camera3D = cameras[entity_id]
                    _apply_camera_state(camera, entry.state as CameraCalibrationState)
                    applied_count += 1

    print("EyeManager: Applied calibration data (%d entries applied)." % applied_count)

## Get list of available actor names from the manifest
func get_actor_names() -> PackedStringArray:
    if not manifest:
        return PackedStringArray()

    var names = manifest.actors.keys()
    names.sort()
    return PackedStringArray(names)

## Request a video texture and UV bounds for a given actor state
## Returns a dictionary with "texture", "uv_offset", and "uv_scale" keys
## Returns empty dict if the clip cannot be found
func get_video_texture_and_uvs(actor_name: String, angle: int, aggravation: int) -> Dictionary:
    if not manifest:
        push_error("EyeManager: No manifest assigned")
        return {}

    var clip = manifest.find_clip(actor_name, angle, aggravation)
    if clip.is_empty():
        push_error("EyeManager: Could not find clip for actor '%s' with angle %d and aggravation %d" % [actor_name, angle, aggravation])
        return {}

    var sheet_id = str(clip.get("sheet_id", ""))
    var sheet_info = manifest.get_sheet_info(sheet_id)
    if sheet_info.is_empty():
        push_error("EyeManager: Could not find sheet info for sheet_id '%s'" % sheet_id)
        return {}

    var sheet_path = sheet_info.get("path", "")
    var sheet_slot = int(clip.get("sheet_slot", 0))

    var vsp = request_video_texture(sheet_path)
    if not vsp:
        return {}

    var uv_bounds = manifest.calculate_uv_bounds(sheet_id, sheet_slot)
    if uv_bounds.is_empty():
        push_error("EyeManager: Could not calculate UV bounds for sheet_id '%s' and slot %d" % [sheet_id, sheet_slot])
        return {}

    return {
        "texture": vsp.get_video_texture(),
        "uv_offset": uv_bounds.get("uv_offset", Vector2.ZERO),
        "uv_scale": uv_bounds.get("uv_scale", Vector2.ONE),
        "aspect_ratio": uv_bounds.get("aspect_ratio", 1.0),
        "video_stream_player": vsp
    }

## Request a video texture by path
## Reference counting keeps the video alive as long as it's needed
func request_video_texture(path: String) -> VideoStreamPlayer:
    if video_pool.has(path):
        video_pool[path].users += 1
        return video_pool[path].player

    var vsp = VideoStreamPlayer.new()
    # Ensure the stream is loaded correctly for the editor
    var stream = load(path)
    if not stream:
        push_error("EyeManager: Could not load stream at " + path)
        return null

    vsp.stream = stream
    vsp.autoplay = true
    vsp.loop = true

    # Add as child to the hidden container to keep it alive but invisible
    _video_container.add_child(vsp)
    vsp.play()

    video_pool[path] = {"player": vsp, "users": 1}
    return vsp

## Release a video texture reference
## When reference count reaches 0, the video is cleaned up
func release_video(path: String):
    if video_pool.has(path):
        video_pool[path].users -= 1
        if video_pool[path].users <= 0:
            var p = video_pool[path].player
            p.stop()
            p.queue_free()
            video_pool.erase(path)

## Release a video stream player directly
func release_video_player(vsp: VideoStreamPlayer):
    if not vsp:
        return

    for path in video_pool.keys():
        if video_pool[path].player == vsp:
            release_video(path)
            return
