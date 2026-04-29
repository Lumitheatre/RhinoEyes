@tool
extends Resource
class_name EyeManifest

@export_file("*.cfg") var config_path: String:
	set(val):
		config_path = val
		_load_manifest()

var config = ConfigFile.new()
var actor_names: Array = []

func _load_manifest():
	if config.load(config_path) == OK:
		actor_names = config.get_sections()
		# Notify any listening EyeNodes that the data has changed
		emit_changed()

func get_actor_list() -> String:
	if actor_names.is_empty(): _load_manifest()
	return ",".join(actor_names)

func get_clip_resource(actor_name: String, angle: float, aggravation: int) -> String:
	var clips = config.get_value(actor_name, "clips", [])
	var best_path: String = ""
	var min_diff: float = 181.0
	
	for clip in clips:
		if clip["enabled"] == "true" and int(clip["aggravation"]) == aggravation:
			var diff = abs(fmod(clip["angle"] - angle + 180, 360) - 180)
			if diff < min_diff:
				min_diff = diff
				best_path = clip["path"]
	
	print_debug("Found clip for %s (Angle: %.2f, Aggravation: %d): %s" % [actor_name, angle, aggravation, best_path])

	return best_path
