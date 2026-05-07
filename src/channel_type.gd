## Enum for sprite sheet channel packing support
class_name ChannelType

enum Type {
	R = 0,      # Red channel
	G = 1,      # Green channel
	B = 2,      # Blue channel
}

## Convert string channel identifier to enum value
static func from_string(channel_str: String) -> int:
	var normalized = channel_str.to_upper().strip_edges()
	match normalized:
		"R":
			return Type.R
		"G":
			return Type.G
		"B":
			return Type.B
		_:
			# Default to R channel
			return Type.R

## Convert enum value back to string representation
static func channel_to_string(channel_type: int) -> String:
	match channel_type:
		Type.R:
			return "R"
		Type.G:
			return "G"
		Type.B:
			return "B"
		_:
			return "R"
