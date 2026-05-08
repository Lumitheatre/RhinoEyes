shader_type spatial;
render_mode blend_mix, cull_back;

uniform vec3 tint_color : source_color = vec3(1.0);
uniform float brightness : hint_range(0.0, 10.0) = 1.0;
uniform sampler2D albedo_texture : hint_default_white;

void fragment() {
	// Sample the base texture
	vec3 base_color = texture(albedo_texture, UV).rgb;

	// Apply tint and brightness
	vec3 emissive = base_color * tint_color * brightness;

	// Set the emissive output
	EMISSION = emissive;

	// Set a simple base color (optional, can be removed if you want pure emissive)
	ALBEDO = base_color;
}
