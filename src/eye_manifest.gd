@tool
extends Resource
class_name EyeManifest

@export_file("*.cfg") var config_file_path: String:
	set(val):
		config_file_path = val
		_parse_manifest()

# Internal storage for parsed data
var actors: Dictionary = {}
var sheets: Dictionary = {}

func _parse_manifest():
	if config_file_path == "": return
	
	var config = ConfigFile.new()
	if config.load(config_file_path) != OK:
		push_error("Manifest Resource: Cannot load CFG.")
		return

	actors.clear()
	sheets.clear()

	var sections = config.get_sections()
	print("All sections: ", sections)
	
	for section in sections:
		var keys = config.get_section_keys(section)
		print("Section '%s' keys: %s" % [section, keys])

	for section in sections:
		if section.begins_with("actor:"):
			actors[section.replace("actor:", "")] = config.get_value(section, "clips", [])
		elif section.begins_with("sheet:"):
			var grid_str = config.get_value(section, "grid", "8x8")
			var grid_parts = grid_str.split("x")
			var grid_width = int(grid_parts[0]) if grid_parts.size() > 0 else 8
			var grid_height = int(grid_parts[1]) if grid_parts.size() > 1 else 8
			
			sheets[section.replace("sheet:", "")] = {
				"path": config.get_value(section, "path", "").strip_edges().replace('"', ''),
				"duration": config.get_value(section, "loop_duration", 30.0),
				"grid_width": grid_width,
				"grid_height": grid_height,
				"fps": config.get_value(section, "fps", 30)
			}

			print("Sheet '%s': path=%s, duration=%.2f, grid=%dx%d, fps=%d" % [
				section.replace("sheet:", ""),
				sheets[section.replace("sheet:", "")].path,
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
		
		# Find the closest angle
		var clip_angle = clip.get("angle", -1)
		var angle_distance = abs(posmod(clip_angle - angle + 180, 360) - 180)
		
		if angle_distance < closest_distance:
			closest_distance = angle_distance
			closest_clip = clip
	
	return closest_clip

## Calculate UV bounds (offset and scale) for a sprite in the sheet
## Returns a dictionary with "uv_offset" (top-left) and "uv_scale" (width/height) in UV space
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
	
	return {
		"uv_offset": uv_offset,
		"uv_scale": uv_scale
	}

## Deprecated: Use calculate_uv_bounds instead
func calculate_uv_offset(sheet_id: String, sheet_slot: int) -> Vector2:
	var bounds = calculate_uv_bounds(sheet_id, sheet_slot)
	if bounds.is_empty():
		return Vector2.ZERO
	return bounds.get("uv_offset", Vector2.ZERO)
