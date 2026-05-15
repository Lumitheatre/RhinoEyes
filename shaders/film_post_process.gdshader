shader_type canvas_item;

// We use hint_screen_texture to grab the 3D scene behind this ColorRect
uniform sampler2D screen_texture : hint_screen_texture, filter_linear, repeat_disable;

// --- Film Stock Controls ---
uniform float desaturation : hint_range(0.0, 1.0) = 1.0;
uniform float sepia_amount : hint_range(0.0, 1.0) = 0.2;
uniform vec3 sepia_color : source_color = vec3(1.0, 0.90, 0.65); // Slightly deeper gold

// --- Film Grain ---
uniform float grain_amount : hint_range(0.0, 1.0) = 0.12;
uniform float grain_scale : hint_range(0.1, 10.0) = 1.2; // Adjusted for 4K
uniform float grain_speed : hint_range(0.0, 10.0) = 2.5;

// --- Film Scratches ---
uniform bool enable_scratches = true;
uniform float scratch_amount : hint_range(0.0, 1.0) = 0.1;
uniform float scratch_density : hint_range(0.0, 1.0) = 0.04;
uniform float scratch_speed : hint_range(0.0, 50.0) = 18.0;

// --- Film Gate Weave/Shake ---
uniform float weave_amount : hint_range(0.0, 0.05) = 0.002; // Lowered: high weave at 4K causes motion sickness
uniform float weave_speed : hint_range(0.0, 100.0) = 1.5;

// --- Vertical Exposure Bleed (film halation) ---
uniform bool enable_bloom = true;
uniform float bloom_strength : hint_range(0.0, 5.0) = 1.0;
uniform float bloom_threshold : hint_range(0.0, 2.0) = 0.8;
uniform float bloom_spread : hint_range(0.0, 32.0) = 2.5; // In screen pixels
uniform float bloom_horizontal_strength : hint_range(0.0, 10.0) = 0.55;
uniform float bloom_vertical_strength : hint_range(0.0, 10.0) = 4.0;
uniform vec3 bloom_tint : source_color = vec3(1.0, 0.96, 0.88); // Warm film halation tint

// --- Vignette ---
uniform float vignette_amount : hint_range(0.0, 1.0) = 0.4;
uniform float vignette_smoothness : hint_range(0.1, 2.0) = 1.2;

float random(vec2 uv, float seed) {
    return fract(sin(dot(uv * (seed + TIME * grain_speed), vec2(12.9898, 78.233))) * 43758.5453);
}

float noise(vec2 uv) {
    vec2 i = floor(uv);
    vec2 f = fract(uv);
    f = f * f * (3.0 - 2.0 * f);
    float a = random(i, 0.0);
    float b = random(i + vec2(1.0, 0.0), 1.0);
    float c = random(i + vec2(0.0, 1.0), 2.0);
    float d = random(i + vec2(1.0, 1.0), 3.0);
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void fragment() {
    // 1. Gate Weave (Subtle UV displacement)
    vec2 weave = vec2(
        sin(TIME * weave_speed) * weave_amount * 0.1,
        cos(TIME * weave_speed * 1.2) * weave_amount * 0.1
    );
    vec2 uv = SCREEN_UV + weave;

    // Clamp to avoid sampling the edge pixels of the screen texture
    uv = clamp(uv, 0.001, 0.999);

    // 2. Sample Base Scene
    vec4 tex = texture(screen_texture, uv);

    // 3. Vertical Exposure Bleed (film halation / overexposure)
    // This is intentionally directional and composited as a bleed, not an additive brightening pass.
    if (enable_bloom) {
        float brightness = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
        float bloom_mask = smoothstep(bloom_threshold, bloom_threshold + 0.35, brightness);

        if (bloom_mask > 0.0) {
            float bleed_accum = 0.0;
            float bleed_weight = 0.0;

            // Vertical sample ladder. Higher ratio = longer streaks.
            // The asymmetry makes it feel more like projected film than a symmetric game bloom.
            for (int i = 1; i <= 6; i++) {
                float fi = float(i);
                float falloff = exp(-fi * 0.85);
                float base_offset = SCREEN_PIXEL_SIZE.y * bloom_spread * fi;
                float up_offset = base_offset * bloom_vertical_strength;
                float down_offset = base_offset * bloom_vertical_strength * 0.55;
                float side_offset = SCREEN_PIXEL_SIZE.x * bloom_spread * fi * bloom_horizontal_strength;

                vec2 up_uv = clamp(uv + vec2(0.0, up_offset), vec2(0.001), vec2(0.999));
                vec2 down_uv = clamp(uv - vec2(0.0, down_offset), vec2(0.001), vec2(0.999));
                vec2 left_uv = clamp(uv - vec2(side_offset, 0.0), vec2(0.001), vec2(0.999));
                vec2 right_uv = clamp(uv + vec2(side_offset, 0.0), vec2(0.001), vec2(0.999));

                vec4 up_sample = texture(screen_texture, up_uv);
                vec4 down_sample = texture(screen_texture, down_uv);
                vec4 left_sample = texture(screen_texture, left_uv);
                vec4 right_sample = texture(screen_texture, right_uv);

                // Luminance-only bloom source: this keeps emissive highlights driving the bleed
                // without dragging the source color into the glow.
                float up_luma = dot(up_sample.rgb, vec3(0.299, 0.587, 0.114));
                float down_luma = dot(down_sample.rgb, vec3(0.299, 0.587, 0.114));
                float left_luma = dot(left_sample.rgb, vec3(0.299, 0.587, 0.114));
                float right_luma = dot(right_sample.rgb, vec3(0.299, 0.587, 0.114));

                float up_mask = smoothstep(bloom_threshold, bloom_threshold + 0.25, up_luma);
                float down_mask = smoothstep(bloom_threshold, bloom_threshold + 0.25, down_luma);
                float left_mask = smoothstep(bloom_threshold, bloom_threshold + 0.25, left_luma);
                float right_mask = smoothstep(bloom_threshold, bloom_threshold + 0.25, right_luma);

                bleed_accum += up_luma * up_mask * falloff * bloom_vertical_strength * 1.15;
                bleed_accum += down_luma * down_mask * falloff * bloom_vertical_strength * 0.65;
                bleed_accum += left_luma * left_mask * falloff * bloom_horizontal_strength * 0.9;
                bleed_accum += right_luma * right_mask * falloff * bloom_horizontal_strength * 0.9;
                bleed_weight += up_mask * falloff * bloom_vertical_strength * 1.15 + down_mask * falloff * bloom_vertical_strength * 0.65 + left_mask * falloff * bloom_horizontal_strength * 0.9 + right_mask * falloff * bloom_horizontal_strength * 0.9;
            }

            if (bleed_weight > 0.0) {
                float bleed_luma = bleed_accum / bleed_weight;
                vec3 bleed_color = vec3(bleed_luma) * bloom_tint;

                // Blend the bleed into the pixel rather than adding to it.
                // This preserves blown highlights and creates a true overexposure glow.
                float bloom_mix = 1.0 - exp(-bloom_strength * bloom_mask);
                tex.rgb = mix(tex.rgb, bleed_color, bloom_mix);
            }
        }
    }

    // 4. Color Grading
    float luma = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
    vec3 color = mix(tex.rgb, vec3(luma), desaturation);
    color = mix(color, luma * sepia_color, sepia_amount);

    // 5. Scratches (Calculated at lower 'frame rate' for film look)
    if (enable_scratches) {
        float frame_time = floor(TIME * scratch_speed);
        float scratch_x = random(vec2(frame_time, 0.0), 15.0);
        if (random(vec2(frame_time, 1.0), 10.0) < scratch_density) {
            float line = smoothstep(0.001, 0.0, abs(uv.x - scratch_x));
            color -= line * scratch_amount;
        }
    }

    // 6. Grain & Vignette
    color += (noise(uv * grain_scale * 100.0 + TIME) - 0.5) * grain_amount;

    float dist = length(uv - 0.5);
    color *= 1.0 - smoothstep(0.4, vignette_smoothness, dist) * vignette_amount;

    COLOR = vec4(color, tex.a);
}
