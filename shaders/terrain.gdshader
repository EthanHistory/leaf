shader_type spatial;

uniform sampler2D noise_tex : repeat_enable;
uniform vec3 grass_a : source_color = vec3(0.30, 0.52, 0.10);
uniform vec3 grass_b : source_color = vec3(0.58, 0.72, 0.20);
uniform vec3 bed_col : source_color = vec3(0.8, 0.78, 0.6);
uniform vec3 mud_col : source_color = vec3(0.36, 0.32, 0.22);
uniform float water_y = -0.2;

varying vec3 wpos;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	float n = texture(noise_tex, wpos.xz * 0.04).r;
	float n2 = texture(noise_tex, wpos.xz * 0.5).r;
	vec3 grass = mix(grass_a, grass_b, smoothstep(0.3, 0.7, n)) * (0.85 + 0.3 * n2);
	vec3 bed = mix(bed_col, mud_col, n2 * 0.6);
	float shore = smoothstep(water_y - 0.02, water_y + 0.3, wpos.y + (n2 - 0.5) * 0.15);
	vec3 bank = mix(mud_col, grass, smoothstep(0.1, 0.5, shore));
	ALBEDO = mix(bed, bank, shore);
	ROUGHNESS = 0.92;
}
