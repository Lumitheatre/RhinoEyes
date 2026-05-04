shader_type spatial;
render_mode unshaded, cull_disabled;

uniform sampler2D video_texture : source_color, filter_linear;
uniform vec2 uv_offset = vec2(0.0, 0.0);   // Top-left corner of the sprite in UV space
uniform vec2 uv_scale = vec2(1.0, 1.0);   // Width and height of the sprite in UV space (0.0-1.0)
uniform float tile_aspect_ratio = 1.0;   // Aspect ratio of the tile (width/height)
uniform vec3 tint : source_color = vec3(1.0);

void fragment() {
	// Apply fit mode with aspect ratio preservation
	// The longest side of the source clip fits exactly (0-1), 
	// the shorter side gets scaled according to aspect ratio
	
	vec2 fit_uv = UV;
	
	if (tile_aspect_ratio < 1.0) {
		// Portrait: tile is taller than wide
		// Keep height at 1.0, scale width by aspect ratio
		fit_uv.x = (fit_uv.x - 0.5) / tile_aspect_ratio + 0.5;
	} else if (tile_aspect_ratio > 1.0) {
		// Landscape: tile is wider than tall
		// Keep width at 1.0, scale height by (1 / aspect ratio)
		fit_uv.y = (fit_uv.y - 0.5) * tile_aspect_ratio + 0.5;
	}
	// If aspect ratio == 1.0, no scaling needed (square tile)
	
	// Apply UV offset and scale to get the correct region of the sprite sheet
	vec2 sprite_uv = fit_uv * uv_scale + uv_offset;
	
	// Check if we're within the tile bounds
	if (sprite_uv.x < uv_offset.x || sprite_uv.x > uv_offset.x + uv_scale.x ||
	    sprite_uv.y < uv_offset.y || sprite_uv.y > uv_offset.y + uv_scale.y) {
		// Outside tile bounds - render black
		ALBEDO = vec3(0.0);
		ALPHA = 0.0;
	} else {
		vec4 tex = texture(video_texture, sprite_uv);
		ALBEDO = tex.rgb * tint;
		ALPHA = tex.a;
	}
}
