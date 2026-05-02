shader_type spatial;
render_mode unshaded, cull_disabled;

uniform sampler2D video_texture : source_color, filter_linear;
uniform vec2 uv_offset = vec2(0.0, 0.0);   // Top-left corner of the sprite in UV space
uniform vec2 uv_scale = vec2(1.0, 1.0);   // Width and height of the sprite in UV space (0.0-1.0)
uniform vec3 tint : source_color = vec3(1.0);

void fragment() {
	// Apply UV offset and scale to get the correct region of the sprite sheet
	vec2 sprite_uv = UV * uv_scale + uv_offset;
	
	vec4 tex = texture(video_texture, sprite_uv);
	
	ALBEDO = tex.rgb * tint;
	ALPHA = tex.a;
}
