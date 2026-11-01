# Credits

## CC-BY 4.0 (attribution required)

- House: "Stylized Medieval House Scene by Jungle Jim"
  (https://sketchfab.com/3d-models/stylized-medieval-house-scene-by-jungle-jim-bb6126de4883448080a3af8fabdbb059)
  by Jungle Jim (https://sketchfab.com/jungle_jim), licensed under CC-BY-4.0
  (http://creativecommons.org/licenses/by/4.0/).
  Modified: showcase ground, sky dome and smoke card removed; meshes joined.
  The generated cottages in assets/houses (tools/build_houses.py) are modelled
  after this house and reuse its brick and wood textures (downscaled), so they
  are derivative works under the same license and credit.

- Bridge: "rope bridge"
  (https://sketchfab.com/3d-models/rope-bridge-a9d56576339a4f31bfb429bb5d40690d)
  by amyvanzi98 (https://sketchfab.com/amyvanzi98), licensed under CC-BY-4.0
  (http://creativecommons.org/licenses/by/4.0/).
  Modified: earth blocks and grass plates removed; meshes joined; rescaled.

## CC0 (no attribution required)

- Trees, bushes, grass and flowers: "Stylized Nature MegaKit" (Standard) by Quaternius
  (https://quaternius.com/packs/stylizednaturemegakit.html).

## Project-owned

- Player character: generated with Tripo (https://www.tripo3d.ai) and rigged with
  idle, walk and run clips (tools/src/heroine_tripo.glb). tools/build_heroine.py
  realigns the painted eyes and brows with the sculpt and gives the hair its own
  mesh and spring-bone chains, writing assets/characters/heroine.glb.
- Leafling (깻잎 숲 몬스터): generated and auto-rigged with Tripo
  (tools/src/creature_tripo.glb). tools/build_leafling.py rebuilds its skinning,
  adds eyelid, mouth, leaf, sprout and tail bones and bakes Idle and Walk clips,
  writing assets/characters/leafling.glb.
- Axe and shield: generated with Tripo (tools/src/axe_tripo.glb, shield_tripo.glb;
  not committed, 60 MB each). tools/build_gear.py decimates them, scales them to
  size and lines them up for mounting, writing assets/gear/.
