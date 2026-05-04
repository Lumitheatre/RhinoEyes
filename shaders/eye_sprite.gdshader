shader_type spatial;
render_mode cull_disabled;

uniform sampler2D video_texture : source_color, filter_linear;
uniform vec2 uv_offset = vec2(0.0, 0.0);
uniform vec2 uv_scale = vec2(0.125, 0.125); // Default to 1/8th for 8x8 grid
uniform float tile_aspect_ratio = 1.0;

// Film Aesthetic Controls
uniform float exposure : hint_range(0.0, 5.0) = 0.8;
uniform float contrast : hint_range(0.0, 3.0) = 1.2;
uniform float emission_strength : hint_range(0.0, 10.0) = 1.0;  // Applied after contrast
uniform vec3 tint : source_color = vec3(1.0);

// Gate Flicker Controls
uniform bool enable_flicker = true;
uniform float flicker_frequency : hint_range(1.0, 30.0) = 15.0;  // Hz (oscillations per second)
uniform float flicker_amplitude : hint_range(0.0, 1.0) = 0.08;   // Brightness variation amount
uniform float flicker_seed : hint_range(0.0, 100000.0) = 43758.5453;  // Random seed for the sine wave

void fragment() {
    // 1. Aspect Ratio Preservation
    vec2 fit_uv = UV;
    if (tile_aspect_ratio < 1.0) {
        // Portrait: scale width
        fit_uv.x = (fit_uv.x - 0.5) / tile_aspect_ratio + 0.5;
    } else if (tile_aspect_ratio > 1.0) {
        // Landscape: scale height
        fit_uv.y = (fit_uv.y - 0.5) * tile_aspect_ratio + 0.5;
    }

    // 2. Sprite Sheet Mapping
    vec2 sprite_uv = fit_uv * uv_scale + uv_offset;

    // 3. Sampling and Bounds Check
    // We strictly clip to the uv_offset/scale range to prevent texture bleeding
    if (fit_uv.x < 0.0 || fit_uv.x > 1.0 || fit_uv.y < 0.0 || fit_uv.y > 1.0) {
        EMISSION = vec3(0.0);
        ALPHA = 0.0;
    } else {
        vec4 tex = texture(video_texture, sprite_uv);

        // 4. Monochromatic Aged Film Logic
        // Convert to luma using standard rec.601 weights
        float luma = dot(tex.rgb, vec3(0.299, 0.587, 0.114));

        // Apply High Contrast and Overexposure (Blowing out the whites)
        luma = pow(luma * exposure, contrast);

        // Apply emission strength after contrast for glow control
        luma *= emission_strength;

        // Calculate Gate Flicker (brightness oscillation effect)
        float flicker = 1.0;
        if (enable_flicker) {
            // Create a pseudo-random sine wave oscillation
            // flicker_frequency controls how fast it oscillates (Hz)
            // flicker_amplitude controls the strength of the effect (0.0 - 1.0)
            // flicker_seed is a magic number that creates good randomness in the sine wave
            flicker = 1.0 + (fract(sin(TIME * flicker_frequency) * flicker_seed) - 0.5) * flicker_amplitude;
        }

        // 5. Final Output
        // Using EMISSION > 1.0 triggers the WorldEnvironment Glow
        EMISSION = vec3(luma * flicker) * tint;
        ALPHA = tex.a;
    }
}
