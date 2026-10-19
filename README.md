# Blender Scene to Python Exporter

`export_scene_as_code.py` reads the scene open in Blender and writes a **standalone Python script** that rebuilds it. Run the generated script in a new, empty Blender file and you get the scene back, with no .blend needed. The generated script is plain text, so it is easy to share, read, and diff in Git.

> **Status:** written for Blender 4.x and not yet tested against a wide range of scenes. Expect to fix a few errors on first use, and please open an issue with the console output if you hit one.

## What it does

The exporter produces a single file, `AGWS-scene-rebuild.py` (rename it however you like). It contains:

- `DATA`: the whole scene as a readable Python dictionary
- a small builder that turns `DATA` back into Blender objects
- a `CLEAN_START` flag at the top of the file

## What it can export

| Area | Covered |
| --- | --- |
| Objects | Meshes, curves, text, lights, cameras, empties; location, rotation, scale, parenting, ray visibility, render/viewport hiding, collections |
| Materials | Shader node trees: every node, its properties, input values, colour ramps and links |
| World | Colour and node tree |
| Geometry nodes | Node groups (interface, nodes, links), modifiers and their input values |
| Modifiers and constraints | Type, name and settings |
| Animation | Drivers (variables, expressions) and keyframes on Blender 4.x |
| Scene settings | Render, Cycles, EEVEE, colour management, frame range, active camera |
| Compositor | Node tree (Blender below 5.0) |

## What it does not export

Each of these is skipped with a warning in the console and listed in the generated file:

- UV maps and image textures
- Curve-mapping nodes
- Shape keys, armatures, particles, simulations
- Node-group panels
- Surface and metaball objects (exported as empties)
- Keyframes and the compositor on Blender 5+
- Scenes other than the active one
- Custom font files (the rebuild needs the font at the same path, otherwise it uses the default font)

Every vertex is written as text, so very high-poly meshes make a huge script. It works best for logos, props and simple scenes.

## Usage

**Export**
1. Open your scene in Blender.
2. Go to the **Scripting** tab, click **Open**, and choose `export_scene_as_code.py`.
3. Click **Run Script**.
4. `AGWS-scene-rebuild.py` is written next to your .blend (or in your home folder if the file is unsaved).

**Rebuild**
1. Open a **new, empty** Blender file.
2. In the **Scripting** tab, open `AGWS-scene-rebuild.py` and click **Run Script**.

## Options

At the top of the generated file:

- `CLEAN_START = True`: deletes all existing objects, collections, materials, node groups, lights, cameras, curves, meshes and worlds first. Set to `False` to merge the scene into an existing file (names may get `.001` suffixes).

## Requirements

- Blender 4.x (targeted). Blender 3.x and 5.x may work partially.
- No add-ons or extra Python packages.

## How it works

1. The exporter walks the scene and serialises each datablock into plain Python values (numbers, strings, lists, dictionaries). Links to other datablocks are stored as references by name.
2. It writes those values into `DATA` and appends a fixed builder.
3. The builder creates datablocks in dependency order (node groups, materials, worlds, object data, collections, objects), then applies parenting, modifiers, constraints, animation and scene settings.
4. Datablocks that point at objects, collections or images are linked in a final pass, once everything exists.

## Troubleshooting

- **Red errors in the Blender console:** copy the message into an issue.
- **A node or setting is missing after rebuild:** check the `warnings` list at the end of `DATA["meta"]` in the generated file.
- **Text looks different:** the original font file was not found, so Blender used its default font.
- **Names have `.001` on the end:** you ran with `CLEAN_START = False` in a file that already had datablocks with those names.

## License

Add your license here (for example MIT).
