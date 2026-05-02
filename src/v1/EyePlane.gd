@tool
extends MeshInstance3D

@export var manifest: EyeManifest:
	set(val):
		manifest = val
		if manifest: manifest.changed.connect(_refresh_video)
		notify_property_list_changed()

@export var video_scale: float = 1.0:
	set(val):
		video_scale = val
		_update_video_transform()

var character_name: String = ""

var look_angle: float = 0.0:
	set(v): look_angle = v; _refresh_video()
	
var aggravation: int = 1
	
var video_player: VideoStreamPlayer

func _get_property_list():
	var properties = []
	var actor_list = manifest.get_actor_list() if manifest else ""
	properties.append({
		"name": "character_name",
		"type": TYPE_STRING,
		"hint": PROPERTY_HINT_ENUM,
		"hint_string": actor_list
	})
	properties.append({"name": "look_angle", "type": TYPE_FLOAT, "hint": PROPERTY_HINT_RANGE, "hint_string": "0,360"})
	properties.append({"name": "aggravation", "type": TYPE_INT, "hint": PROPERTY_HINT_RANGE, "hint_string": "1,3"})
	return properties

func _ready():
	_setup_video_player()
	_refresh_video()

func _setup_video_player():
	if has_node("VPlayer"):
		video_player = get_node("VPlayer")
	else:
		video_player = VideoStreamPlayer.new()
		video_player.name = "VPlayer"
		add_child(video_player)
		video_player.loop = true
		video_player.autoplay = true
	
	_update_video_transform()
	var mat = get_active_material(0)
	if mat is ShaderMaterial:
		mat.set_shader_parameter("video_texture", video_player.get_video_texture())

func _update_video_transform():
	if not video_player: return
	video_player.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	video_player.scale = Vector2(video_scale, video_scale)
	video_player.pivot_offset = video_player.size / 2.0

func _refresh_video():
	if not video_player or not manifest or character_name == "": return
	var path = manifest.get_clip_resource(character_name, look_angle, aggravation)
	if path != "" and (not video_player.stream or video_player.stream.resource_path != path):
		video_player.stream = load(path)
		video_player.play()
		_update_video_transform()
