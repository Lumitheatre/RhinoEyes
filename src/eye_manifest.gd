@tool
extends Resource
class_name EyeManifest

@export_file("*.cfg") var config_file_path: String:
	set(val):
		config_file_path = val
		_parse_manifest()
		_setup_file_watcher()

# Internal storage for parsed data
var actors: Dictionary = {}
var sheets: Dictionary = {}
var _last_modified_time: int = 0
var _poll_interval: float = 1.0  # Check every 1 second

func _ready():
	# Initialize file watcher in editor mode only
	if Engine.is_editor_hint():
		call_deferred("_setup_file_watcher")
	_parse_manifest()

func _setup_file_watcher():
	# Only works in editor and if config file is set
	if not Engine.is_editor_hint() or config_file_path == "":
		return

	# Store initial modification time
	if FileAccess.file_exists(config_file_path):
		_last_modified_time = FileAccess.get_modified_time(config_file_path)

	print("EyeManifest: File watcher started for '%s' (polling every %.1f seconds)" % [config_file_path, _poll_interval])
	_start_monitoring()

func _start_monitoring():
	# Only set up monitoring in editor
	if not Engine.is_editor_hint() or config_file_path == "":
		return

	# Create a main loop timer that doesn't need to be added to the tree
	var timer = Engine.get_main_loop().create_timer(_poll_interval)
	timer.timeout.connect(_on_check_file_modified)

func _on_check_file_modified():
	# Safety check
	if config_file_path == "" or not FileAccess.file_exists(config_file_path):
		_start_monitoring()  # Restart monitoring even if file doesn't exist yet
		return

	# Check if file has been modified
	var current_modified_time = FileAccess.get_modified_time(config_file_path)
	if current_modified_time > _last_modified_time:
		_last_modified_time = current_modified_time
		print("EyeManifest: Config file %s modified, reloading manifest..." % config_file_path)
		_parse_manifest()

	# Restart the monitoring
	_start_monitoring()

## Manual reload function for user to call from editor
func reload_manifest():
	print("EyeManifest: Manual reload requested")
	_parse_manifest()

func _parse_manifest():
	if config_file_path == "": return

	var config = ConfigFile.new()
	if config.load(config_file_path) != OK:
		push_error("Manifest Resource: Cannot load CFG.")
		return

	actors.clear()
	sheets.clear()

	var sections = config.get_sections()

	for section in sections:
		var keys = config.get_section_keys(section)

	for section in sections:
		if section.begins_with("actor:"):
			actors[section.replace("actor:", "")] = config.get_value(section, "clips", [])
		elif section.begins_with("sheet:"):
			var grid_str = config.get_value(section, "grid", "8x8")
			var grid_parts = grid_str.split("x")
			var grid_width = int(grid_parts[0]) if grid_parts.size() > 0 else 8
			var grid_height = int(grid_parts[1]) if grid_parts.size() > 1 else 8

			var resolution = config.get_value(section, "resolution", "512x512")
			var res_parts = resolution.split("x")
			var res_width = int(res_parts[0]) if res_parts.size() > 0 else 512
			var res_height = int(res_parts[1]) if res_parts.size() > 1 else 512

			sheets[section.replace("sheet:", "")] = {
				"path": config.get_value(section, "path", "").strip_edges().replace('"', ''),
				"duration": config.get_value(section, "loop_duration", 30.0),
				"grid_width": grid_width,
				"grid_height": grid_height,
				"fps": config.get_value(section, "fps", 30),
				"res_width": res_width,
				"res_height": res_height,
			}

			print("Sheet '%s': path=%s, resolution %dx%d, duration=%.2f, grid=%dx%d, fps=%d" % [
				section.replace("sheet:", ""),
				sheets[section.replace("sheet:", "")].path,
				res_width,
				res_height,
				sheets[section.replace("sheet:", "")].duration,
				grid_width,
				grid_height,
				sheets[section.replace("sheet:", "")].fps
			])
	emit_changed() # Notify the Inspector/Actors that data has updated

## Get sheet info by sheet ID
func get_sheet_info(sheet_id: String) -> Dictionary:
	return sheets.get(sheet_id, {})

## Get clip data for an actor
func get_actor_clips(actor_name: String) -> Array:
	return actors.get(actor_name, [])

## Find a clip by actor, angle, and aggravation
## Finds the closest available angle for the given aggravation level
## Only returns enabled clips. Aggravation must match exactly.
## Converts sheet_channel string to ChannelType enum value.
func find_clip(actor_name: String, angle: int, aggravation: int) -> Dictionary:
	var clips = actors.get(actor_name, [])
	var closest_clip = {}
	var closest_distance = INF

	for clip in clips:
		# Skip disabled clips
		if not clip.get("enabled", true):
			continue

		# Aggravation must match exactly
		if clip.get("aggravation", 1) != aggravation:
			continue

		# Angle -1 is a special "look at camera" state, exclude from nearest angle search
		if clip["angle"] == -1:
			continue

		# Find the closest angle
		var clip_angle = clip.get("angle", -1)
		var angle_distance = abs(posmod(clip_angle - angle + 180, 360) - 180)

		if angle_distance < closest_distance:
			closest_distance = angle_distance
			closest_clip = clip

	# Convert sheet_channel string to enum value
	if not closest_clip.is_empty() and closest_clip.has("sheet_channel"):
		closest_clip["sheet_channel"] = ChannelType.from_string(str(closest_clip["sheet_channel"]))
	else:
		closest_clip["sheet_channel"] = ChannelType.Type.R

	return closest_clip

## Calculate UV bounds (offset and scale) for a sprite in the sheet
## Returns a dictionary with "uv_offset" (top-left), "uv_scale" (width/height) in UV space,
## and "aspect_ratio" (width/height) of the tile
func calculate_uv_bounds(sheet_id: String, sheet_slot: int) -> Dictionary:
	var sheet_info = get_sheet_info(sheet_id)
	if sheet_info.is_empty():
		return {}

	var grid_width = sheet_info.get("grid_width", 8)
	var grid_height = sheet_info.get("grid_height", 8)

	# Calculate tile size in UV space
	var tile_width = 1.0 / float(grid_width)
	var tile_height = 1.0 / float(grid_height)

	# Calculate which tile this slot is
	var slot_x = sheet_slot % grid_width
	var slot_y = sheet_slot / grid_width

	# Calculate UV offset (top-left corner of this tile)
	var uv_offset = Vector2(
		float(slot_x) * tile_width,
		float(slot_y) * tile_height
	)

	# UV scale is the tile size
	var uv_scale = Vector2(tile_width, tile_height)

	# Calculate tile aspect ratio from spreadsheet resolution and grid
	var res_width = float(sheet_info.get("res_width", 512))
	var res_height = float(sheet_info.get("res_height", 512))
	var tile_aspect_ratio = (res_width / float(grid_width)) / (res_height / float(grid_height))

	return {
		"uv_offset": uv_offset,
		"uv_scale": uv_scale,
		"aspect_ratio": tile_aspect_ratio
	}
