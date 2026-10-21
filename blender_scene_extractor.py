"""
Dump the open Blender scene as a compact, human/AI-readable text file.

Run:    Scripting tab > Open (or paste) > Run Script
Output: AGWS-scene-dump.txt next to the .blend (home folder if the file is unsaved).

Purpose: explain the scene to an AI model. No vertex data - only structure:
scene settings, collections, objects, modifiers (incl. Geometry Nodes inputs),
constraints, animation/drivers, materials and node trees (nodes + links), node groups, world.
Every section is wrapped in try/except, so one odd datablock can't stop the export.
"""
import bpy, os

OUT = []
WARN = []


def w(line="", indent=0):
    OUT.append("  " * indent + line)


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def fmt(v):
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return str(round(v, 4))
    if isinstance(v, (int, str)):
        return repr(v) if isinstance(v, str) else str(v)
    if isinstance(v, bpy.types.ID):
        return "<%s '%s'>" % (v.id_type, v.name)
    try:
        return "(" + ", ".join(fmt(x) for x in v) + ")"
    except TypeError:
        return "<%s>" % type(v).__name__


def simple_props(struct, skip=(), only_non_default=False):
    """name=value pairs for simple writable properties."""
    out = []
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in skip or k == "rna_type" or p.is_readonly:
            continue
        try:
            if p.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                v = getattr(struct, k)
                if p.type == "ENUM" and p.is_enum_flag:
                    v = sorted(v)
                    out.append("%s=%s" % (k, v))
                    continue
                if only_non_default and p.type != "STRING":
                    dv = p.default_array if getattr(p, "is_array", False) else p.default
                    if v == dv or (hasattr(v, "__len__") and tuple(v) == tuple(dv)):
                        continue
                out.append("%s=%s" % (k, fmt(v)))
            elif p.type == "POINTER":
                v = getattr(struct, k)
                if isinstance(v, bpy.types.ID):
                    out.append("%s=%s" % (k, fmt(v)))
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ node trees
def dump_tree(tree, indent=1):
    nodes = list(tree.nodes)
    w("Nodes (%d):" % len(nodes), indent)
    for n in nodes:
        head = "%s  [%s]" % (n.name, n.bl_idname)
        if n.label:
            head += " label='%s'" % n.label
        if n.mute:
            head += " MUTED"
        if n.parent:
            head += " in frame '%s'" % n.parent.name
        w("- " + head, indent + 1)
        props = simple_props(n, skip={"name", "label", "location", "width", "height", "dimensions", "select",
                                      "show_options", "show_preview", "hide", "mute", "show_texture",
                                      "use_custom_color", "color", "bl_idname", "bl_label", "bl_description",
                                      "bl_icon", "bl_static_type", "bl_width_default", "bl_width_min",
                                      "bl_width_max", "bl_height_default", "bl_height_min", "bl_height_max"},
                             only_non_default=True)
        if props:
            w("settings: " + ", ".join(props), indent + 3)
        vals = []
        for s in n.inputs:
            if s.is_linked or not hasattr(s, "default_value") or not s.enabled:
                continue
            v = safe(lambda: s.default_value)
            vals.append("%s=%s" % (s.name, fmt(v)))
        if vals:
            w("inputs: " + ", ".join(vals), indent + 3)
        cr = getattr(n, "color_ramp", None)
        if cr is not None:
            w("color ramp (%s): %s" % (cr.interpolation,
              " | ".join("%.3f:%s" % (e.position, fmt(e.color)) for e in cr.elements)), indent + 3)
        if hasattr(n, "mapping"):
            w("(curve mapping not detailed)", indent + 3)
        if n.bl_idname == "ShaderNodeTexImage" and getattr(n, "image", None):
            w("image: %s (%s)" % (n.image.name, n.image.filepath), indent + 3)
    links = list(tree.links)
    w("Links (%d):" % len(links), indent)
    for l in links:
        w("%s.%s -> %s.%s" % (l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name),
          indent + 1)


def dump_interface(tree, indent=1):
    iface = getattr(tree, "interface", None)
    if iface is None:
        return
    w("Interface:", indent)
    for it in iface.items_tree:
        if it.item_type != "SOCKET":
            w("- [panel] %s" % it.name, indent + 1)
            continue
        extra = ""
        if hasattr(it, "default_value"):
            extra = " default=%s" % fmt(safe(lambda: it.default_value))
        for k in ("min_value", "max_value"):
            if hasattr(it, k):
                extra += " %s=%s" % (k, fmt(safe(lambda: getattr(it, k))))
        w("- %s %s (%s)%s" % (it.in_out, it.name, it.socket_type, extra), indent + 1)


# ------------------------------------------------------------------ animation
def dump_anim(idb, indent):
    ad = getattr(idb, "animation_data", None)
    if ad is None:
        return
    if ad.action:
        fcs = safe(lambda: list(ad.action.fcurves))
        if fcs is None:
            w("animation: action '%s' (layered action - keyframes not listed)" % ad.action.name, indent)
        else:
            w("animation: action '%s', %d fcurves" % (ad.action.name, len(fcs)), indent)
            for fc in fcs:
                pts = fc.keyframe_points
                if len(pts):
                    rng = "frames %.0f-%.0f" % (pts[0].co[0], pts[-1].co[0])
                    vals = "values %s -> %s" % (fmt(pts[0].co[1]), fmt(pts[-1].co[1]))
                else:
                    rng, vals = "no keys", ""
                mods = ",".join(m.type for m in fc.modifiers)
                w("%s[%d]: %d keys, %s, %s%s" % (fc.data_path, fc.array_index, len(pts), rng, vals,
                                                 (" modifiers=" + mods) if mods else ""), indent + 1)
    for fc in ad.drivers:
        d = fc.driver
        vs = []
        for v in d.variables:
            tg = v.targets[0] if len(v.targets) else None
            vs.append("%s=%s:%s" % (v.name, fmt(tg.id) if tg else "?", tg.data_path if tg else ""))
        w("driver %s[%d]: %s '%s' vars: %s" % (fc.data_path, fc.array_index, d.type, d.expression,
                                              "; ".join(vs)), indent)


# ------------------------------------------------------------------ objects
def dump_modifier(m, indent):
    w("- %s [%s]" % (m.name, m.type), indent)
    props = simple_props(m, skip={"name", "type", "node_group", "is_override_data", "persistent_uid"},
                         only_non_default=True)
    if props:
        w(", ".join(props), indent + 2)
    if m.type == "NODES":
        ng = m.node_group
        w("node group: %s" % (ng.name if ng else "None"), indent + 2)
        if ng is not None and hasattr(ng, "interface"):
            vals = []
            for it in ng.interface.items_tree:
                if it.item_type == "SOCKET" and it.in_out == "INPUT":
                    try:
                        vals.append("%s=%s" % (it.name, fmt(m[it.identifier])))
                    except Exception:
                        pass
            if vals:
                w("inputs: " + ", ".join(vals), indent + 2)
            else:
                w("(input values not readable in this Blender version)", indent + 2)


def dump_object(o):
    w("")
    w("OBJECT '%s'  type=%s" % (o.name, o.type), 0)
    w("location=%s rotation(%s)=%s scale=%s" % (
        fmt(o.location), o.rotation_mode,
        fmt(o.rotation_quaternion if o.rotation_mode == "QUATERNION" else o.rotation_euler),
        fmt(o.scale)), 1)
    w("dimensions=%s" % fmt(o.dimensions), 1)
    if o.parent:
        w("parent='%s' (%s)" % (o.parent.name, o.parent_type), 1)
    w("collections: %s" % ", ".join(c.name for c in o.users_collection), 1)
    flags = []
    if o.hide_viewport:
        flags.append("hidden in viewport")
    if o.hide_render:
        flags.append("hidden in render")
    if flags:
        w("visibility: " + ", ".join(flags), 1)
    d = o.data
    if d is not None:
        w("data: %s '%s'" % (type(d).__name__, d.name), 1)
    if o.type == "MESH" and d is not None:
        w("mesh: %d verts, %d edges, %d faces; uv maps: %s; shape keys: %s" % (
            len(d.vertices), len(d.edges), len(d.polygons),
            ", ".join(u.name for u in d.uv_layers) or "none",
            ", ".join(k.name for k in d.shape_keys.key_blocks) if d.shape_keys else "none"), 1)
    elif o.type == "FONT" and d is not None:
        w("text body: %r" % d.body, 1)
        w("text: size=%s extrude=%s font=%s" % (round(d.size, 4), round(d.extrude, 4),
                                                d.font.name if d.font else "default"), 1)
    elif o.type == "CURVE" and d is not None:
        w("curve: %d splines, %s" % (len(d.splines), ", ".join(s.type for s in d.splines)), 1)
    elif o.type == "LIGHT" and d is not None:
        w("light: type=%s energy=%s color=%s" % (d.type, round(d.energy, 4), fmt(d.color)), 1)
    elif o.type == "CAMERA" and d is not None:
        w("camera: type=%s lens=%s sensor=%s clip=%s..%s" % (
            d.type, round(d.lens, 3), round(d.sensor_width, 3), round(d.clip_start, 4), round(d.clip_end, 1)), 1)
    mats = [s.material.name if s.material else "(empty)" for s in o.material_slots]
    if mats:
        w("materials: " + ", ".join(mats), 1)
    if o.modifiers:
        w("modifiers:", 1)
        for m in o.modifiers:
            safe(lambda: dump_modifier(m, 2)) is None and None
    if o.constraints:
        w("constraints:", 1)
        for c in o.constraints:
            w("- %s [%s] %s" % (c.name, c.type, ", ".join(simple_props(c, {"name", "type"}, True))), 2)
    safe(lambda: dump_anim(o, 1))


def dump_collection(c, indent):
    w("- %s (%d objects)" % (c.name, len(c.objects)), indent)
    for ch in c.children:
        dump_collection(ch, indent + 1)


# ------------------------------------------------------------------ main
scene = bpy.context.scene
r = scene.render
w("BLENDER SCENE DUMP")
w("blender version: %s" % bpy.app.version_string)
w("file: %s" % (os.path.basename(bpy.data.filepath) or "(unsaved)"))
w("")
w("== SCENE ==")
w("name: %s" % scene.name)
w("render engine: %s" % r.engine)
w("resolution: %dx%d at %d%%, fps=%d" % (r.resolution_x, r.resolution_y, r.resolution_percentage, r.fps))
w("frames: %d-%d (current %d)" % (scene.frame_start, scene.frame_end, scene.frame_current))
w("camera: %s" % (scene.camera.name if scene.camera else "None"))
w("world: %s" % (scene.world.name if scene.world else "None"))
w("colour management: view=%s look=%s display=%s" % (
    scene.view_settings.view_transform, scene.view_settings.look, scene.display_settings.display_device))
for key in ("cycles", "eevee"):
    s = getattr(scene, key, None)
    if s is not None:
        p = safe(lambda: simple_props(s, only_non_default=True), [])
        w("%s settings (non-default): %s" % (key, ", ".join(p)))
safe(lambda: dump_anim(scene, 0))

w("")
w("== COLLECTIONS ==")
dump_collection(scene.collection, 0)

w("")
w("== OBJECTS (%d) ==" % len(scene.objects))
for o in scene.objects:
    try:
        dump_object(o)
    except Exception as e:
        w("(failed to dump object '%s': %s)" % (o.name, e))
        WARN.append(o.name)

w("")
w("== MATERIALS (%d) ==" % len(bpy.data.materials))
for m in bpy.data.materials:
    w("")
    w("MATERIAL '%s' (users: %d)" % (m.name, m.users), 0)
    try:
        if m.use_nodes and m.node_tree:
            dump_tree(m.node_tree)
            safe(lambda: dump_anim(m.node_tree, 1))
        else:
            w("no node tree; diffuse_color=%s" % fmt(m.diffuse_color), 1)
    except Exception as e:
        w("(failed: %s)" % e, 1)

w("")
w("== NODE GROUPS (%d) ==" % len(bpy.data.node_groups))
for g in bpy.data.node_groups:
    w("")
    w("NODE GROUP '%s' [%s] (users: %d)" % (g.name, g.bl_idname, g.users), 0)
    try:
        dump_interface(g)
        dump_tree(g)
    except Exception as e:
        w("(failed: %s)" % e, 1)

w("")
w("== WORLDS ==")
for wd in bpy.data.worlds:
    w("WORLD '%s' color=%s" % (wd.name, fmt(wd.color)), 0)
    try:
        if wd.use_nodes and wd.node_tree:
            dump_tree(wd.node_tree)
    except Exception as e:
        w("(failed: %s)" % e, 1)

if bpy.app.version < (5, 0, 0):
    try:
        if scene.use_nodes and scene.node_tree:
            w("")
            w("== COMPOSITOR ==")
            dump_tree(scene.node_tree)
    except Exception as e:
        w("(compositor failed: %s)" % e)

base = bpy.path.abspath("//") if bpy.data.filepath else os.path.expanduser("~")
path = os.path.join(base, "AGWS-scene-dump.txt")
with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT))
print("Scene dump written:", path, "(%d lines)" % len(OUT))
