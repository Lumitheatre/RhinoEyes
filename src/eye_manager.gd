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
@export var target_node: Node3D

# This is the position in world space the target_node is seeking to reach
var destination_pos: Vector3

@export var target_lerp_speed: float = 5.0
@export var target_plane_offset: float = 0.0 # The height of the "stage" floor

var _target_tween: Tween

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

func get_target_position() -> Vector3:
    if target_node:
        return target_node.global_transform.origin
    return destination_pos

func _input(event):
    # Handle Mouse Click or Touchscreen Tap
    if event is InputEventMouseButton or event is InputEventScreenTouch:
        if event.pressed:
            update_destination(event.position)

func _process(delta):
    # Continuously tween towards the destination position for smooth movement
    if target_node and destination_pos:
        var current_pos = target_node.global_transform.origin
        target_node.global_transform.origin = current_pos.lerp(destination_pos, target_lerp_speed * delta)

func update_destination(screen_pos: Vector2):
    var cam = get_viewport().get_camera_3d()
    var ray_origin = cam.project_ray_origin(screen_pos)
    var ray_dir = cam.project_ray_normal(screen_pos)

    # Project the click onto the XY plane (Z = 0)
    # Intersection of ray and plane: t = -origin.z / dir.z
    if ray_dir.z != 0:
        var t = (target_plane_offset - ray_origin.z) / ray_dir.z
        destination_pos = ray_origin + ray_dir * t

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
