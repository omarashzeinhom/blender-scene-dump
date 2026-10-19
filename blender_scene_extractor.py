"""
Export the WHOLE open Blender file as a self-contained Python script.

Run:   Scripting tab > Open > Run Script   (in the finished AGWS file)
Output: AGWS-scene-rebuild.py next to the .blend (or in your home folder if unsaved).

To rebuild: open a NEW empty Blender file, load AGWS-scene-rebuild.py, Run Script.
The generated file contains the scene as a DATA dictionary plus a small builder, so it
is readable, shareable and diff-able.

Covered: objects (transforms, parenting, visibility, collections), meshes, curves, text,
lights, cameras, empties, materials (full node trees), world, geometry-node groups
(interface + nodes + links), modifiers (incl. Geometry Nodes inputs), constraints,
drivers and keyframes, render / Cycles / colour-management settings, compositor (< 5.0).

Not covered (a warning is printed and stored in the file): UV maps, images/textures,
curve-mapping nodes, shape keys, armatures, particles, node-group panels, and keyframes
on Blender 5+ (layered actions).
Tested design target: Blender 4.x.
"""
import bpy, os, pprint
from mathutils import Vector, Color, Euler, Quaternion, Matrix

WARN = []

def warn(msg):
    WARN.append(msg)
    print("WARN:", msg)

def rnd(x):
    return round(float(x), 6)

# ------------------------------------------------------------------ generic serialisation
def ser(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return rnd(v)
    if isinstance(v, bpy.types.ID):
        return {"$ref": [v.id_type, v.name]}
    if isinstance(v, (Vector, Color, Euler, Quaternion)):
        return [rnd(x) for x in v]
    if isinstance(v, Matrix):
        return [[rnd(x) for x in row] for row in v]
    try:
        return [ser(x) for x in v]
    except TypeError:
        warn("could not serialise value of type %s" % type(v).__name__)
        return None

def props_simple(struct, skip=()):
    """Writable simple properties (bool/int/float/string/enum) and ID pointers."""
    d = {}
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in skip or k == "rna_type" or k.startswith("bl_") or p.is_readonly:
            continue
        try:
            if p.type in {"BOOLEAN", "INT", "FLOAT", "STRING"}:
                d[k] = ser(getattr(struct, k))
            elif p.type == "ENUM" and not p.is_enum_flag:
                d[k] = getattr(struct, k)
            elif p.type == "POINTER":
                v = getattr(struct, k)
                if isinstance(v, bpy.types.ID):
                    d[k] = ser(v)
        except Exception:
            pass
    return d

# ------------------------------------------------------------------ animation
def iter_fcurves(action):
    try:
        return list(action.fcurves)
    except Exception:
        warn("keyframes of action '%s' not exported (layered actions in this Blender version)" % action.name)
        return []

def ser_anim(idb):
    ad = getattr(idb, "animation_data", None)
    if ad is None:
        return None
    out = {"fcurves": [], "drivers": []}
    if ad.action:
        for fc in iter_fcurves(ad.action):
            out["fcurves"].append({
                "data_path": fc.data_path,
                "array_index": fc.array_index,
                "extrapolation": fc.extrapolation,
                "keys": [{"co": ser(k.co), "interp": k.interpolation,
                          "hl": ser(k.handle_left), "hr": ser(k.handle_right),
                          "tl": k.handle_left_type, "tr": k.handle_right_type}
                         for k in fc.keyframe_points],
                "modifiers": [{"type": m.type, "props": props_simple(m, {"type"})} for m in fc.modifiers],
            })
    for fc in ad.drivers:
        drv = fc.driver
        out["drivers"].append({
            "data_path": fc.data_path,
            "array_index": fc.array_index,
            "type": drv.type,
            "expression": drv.expression,
            "use_self": drv.use_self,
            "vars": [{
                "name": v.name,
                "type": v.type,
                "targets": [{"id_type": t.id_type, "id": ser(t.id), "data_path": t.data_path,
                             "transform_type": t.transform_type, "transform_space": t.transform_space,
                             "rotation_mode": t.rotation_mode, "bone_target": t.bone_target}
                            for t in v.targets],
            } for v in drv.variables],
        })
    return out if (out["fcurves"] or out["drivers"]) else None

# ------------------------------------------------------------------ node trees
NODE_SKIP = {"name", "label", "location", "width", "height", "dimensions", "select", "show_options",
             "show_preview", "hide", "mute", "show_texture", "use_custom_color", "color", "type"}

def ser_interface(tree):
    items = []
    iface = getattr(tree, "interface", None)
    if iface is None:
        warn("node group '%s': interface not exported (Blender < 4.0)" % tree.name)
        return items
    for it in iface.items_tree:
        if it.item_type != "SOCKET":
            warn("node group '%s': panel '%s' skipped" % (tree.name, it.name))
            continue
        d = {"name": it.name, "description": it.description, "in_out": it.in_out, "socket_type": it.socket_type}
        for k in ("subtype", "min_value", "max_value", "default_value", "hide_value"):
            if hasattr(it, k):
                try:
                    d[k] = ser(getattr(it, k))
                except Exception:
                    pass
        items.append(d)
    return items

def ser_tree(tree):
    t = {"name": tree.name, "bl_idname": tree.bl_idname, "nodes": [], "links": []}
    if hasattr(tree, "interface") and tree.bl_idname in {"GeometryNodeTree", "ShaderNodeTree", "CompositorNodeTree"}:
        if tree.users and tree.name in bpy.data.node_groups:
            t["interface"] = ser_interface(tree)
    for n in tree.nodes:
        nd = {
            "name": n.name, "bl_idname": n.bl_idname, "label": n.label,
            "location": [rnd(n.location.x), rnd(n.location.y)], "width": rnd(n.width),
            "mute": n.mute, "hide": n.hide,
            "parent": n.parent.name if n.parent else None,
            "props": props_simple(n, NODE_SKIP),
            "inputs": {}, "outputs": {},
        }
        for i, s in enumerate(n.inputs):
            if hasattr(s, "default_value"):
                try:
                    nd["inputs"][i] = ser(s.default_value)
                except Exception:
                    pass
        for i, s in enumerate(n.outputs):
            if hasattr(s, "default_value"):
                try:
                    nd["outputs"][i] = ser(s.default_value)
                except Exception:
                    pass
        if hasattr(n, "color_ramp") and n.color_ramp is not None:
            cr = n.color_ramp
            nd["ramp"] = {"color_mode": cr.color_mode, "interpolation": cr.interpolation,
                          "hue": cr.hue_interpolation,
                          "elements": [{"pos": rnd(e.position), "color": ser(e.color)} for e in cr.elements]}
        if hasattr(n, "mapping"):
            warn("node '%s' (%s): curve mapping not exported" % (n.name, tree.name))
        t["nodes"].append(nd)
    for l in tree.links:
        try:
            t["links"].append({
                "from": l.from_node.name, "from_i": list(l.from_node.outputs).index(l.from_socket),
                "to": l.to_node.name, "to_i": list(l.to_node.inputs).index(l.to_socket),
            })
        except ValueError:
            pass
    return t

# ------------------------------------------------------------------ datablocks
SUPPORTED = {"MESH", "FONT", "CURVE", "LIGHT", "CAMERA", "EMPTY"}

def ser_material(m):
    d = {"name": m.name, "props": props_simple(m, {"name", "use_nodes"}), "tree": None, "anim": None}
    if m.use_nodes and m.node_tree:
        d["tree"] = ser_tree(m.node_tree)
        d["anim"] = ser_anim(m.node_tree)
    return d

def ser_world(w):
    d = {"name": w.name, "color": ser(w.color), "tree": None, "anim": None}
    if w.use_nodes and w.node_tree:
        d["tree"] = ser_tree(w.node_tree)
        d["anim"] = ser_anim(w.node_tree)
    return d

def ser_spline(sp):
    d = {"type": sp.type, "cyclic": sp.use_cyclic_u, "resolution": sp.resolution_u, "points": []}
    if sp.type == "BEZIER":
        for bp in sp.bezier_points:
            d["points"].append({"co": ser(bp.co), "hl": ser(bp.handle_left), "hr": ser(bp.handle_right),
                                "tl": bp.handle_left_type, "tr": bp.handle_right_type,
                                "radius": rnd(bp.radius), "tilt": rnd(bp.tilt)})
    else:
        for pt in sp.points:
            d["points"].append({"co": ser(pt.co), "radius": rnd(pt.radius), "tilt": rnd(pt.tilt)})
        if sp.type == "NURBS":
            d["order_u"] = sp.order_u
            d["use_endpoint_u"] = sp.use_endpoint_u
    return d

def ser_data(o):
    d = o.data
    rec = {"type": o.type, "name": d.name, "anim": ser_anim(d)}
    if hasattr(d, "materials"):
        rec["materials"] = [m.name if m else None for m in d.materials]
    if o.type == "MESH":
        rec["verts"] = [[rnd(c) for c in v.co] for v in d.vertices]
        rec["faces"] = [list(p.vertices) for p in d.polygons]
        rec["mat_index"] = [p.material_index for p in d.polygons]
        rec["smooth"] = [p.use_smooth for p in d.polygons]
        if not d.polygons:
            rec["edges"] = [list(e.vertices) for e in d.edges]
        if d.uv_layers:
            warn("mesh '%s': UV maps not exported" % d.name)
    elif o.type in {"FONT", "CURVE"}:
        rec["props"] = props_simple(d)
        rec["splines"] = [ser_spline(sp) for sp in d.splines] if o.type == "CURVE" else []
        if o.type == "FONT":
            rec["fonts"] = []
            for slot in ("font", "font_bold", "font_italic", "font_bold_italic"):
                f = getattr(d, slot, None)
                if f and f.filepath != "<builtin>":
                    rec["fonts"].append({"slot": slot, "name": f.name, "filepath": f.filepath})
    elif o.type == "LIGHT":
        rec["light_type"] = d.type
        rec["props"] = props_simple(d)
    elif o.type == "CAMERA":
        rec["props"] = props_simple(d)
        rec["dof"] = props_simple(d.dof)
    return rec

def ser_modifier(m):
    d = {"name": m.name, "type": m.type, "props": props_simple(m, {"name", "type"})}
    if m.type == "NODES":
        d["node_group"] = ser(m.node_group)
        inputs = {}
        for k in m.keys():
            try:
                inputs[k] = ser(m[k])
            except Exception:
                pass
        d["inputs"] = inputs
    return d

def ser_object(o, scene):
    t = o.type if o.type in SUPPORTED else "EMPTY"
    if o.type not in SUPPORTED:
        warn("object '%s': type %s not supported, exported as empty" % (o.name, o.type))
    cols = []
    for c in o.users_collection:
        cols.append("$master" if c == scene.collection else c.name)
    d = {
        "name": o.name, "type": t,
        "data": o.data.name if (o.data is not None and t != "EMPTY") else None,
        "loc": ser(o.location), "rot_mode": o.rotation_mode,
        "rot_euler": ser(o.rotation_euler), "rot_quat": ser(o.rotation_quaternion),
        "scale": ser(o.scale),
        "parent": o.parent.name if o.parent else None,
        "parent_type": o.parent_type,
        "parent_inverse": ser(o.matrix_parent_inverse),
        "flags": {k: getattr(o, k) for k in (
            "hide_render", "hide_viewport", "hide_select", "display_type",
            "visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission",
            "visible_volume_scatter", "visible_shadow") if hasattr(o, k)},
        "collections": cols,
        "modifiers": [ser_modifier(m) for m in o.modifiers],
        "constraints": [{"name": c.name, "type": c.type, "props": props_simple(c, {"name", "type"})}
                        for c in o.constraints],
        "anim": ser_anim(o),
    }
    if t == "EMPTY":
        d["empty"] = {"empty_display_type": o.empty_display_type, "empty_display_size": rnd(o.empty_display_size)}
    for s in o.material_slots:
        if s.link == "OBJECT" and s.material:
            warn("object '%s': object-linked material slot not exported" % o.name)
    return d

# ------------------------------------------------------------------ collect everything
scene = bpy.context.scene
data = {"meta": {"blender": bpy.app.version_string,
                 "source": os.path.basename(bpy.data.filepath) or "(unsaved)"},
        "groups": {}, "materials": {}, "worlds": {}, "datas": [], "collections": [],
        "master_children": [c.name for c in scene.collection.children],
        "objects": [], "scene": {}}

for g in bpy.data.node_groups:
    td = ser_tree(g)
    td["anim"] = ser_anim(g)
    data["groups"][g.name] = td

for m in bpy.data.materials:
    if getattr(m, "is_grease_pencil", False):
        continue
    data["materials"][m.name] = ser_material(m)

for w in bpy.data.worlds:
    data["worlds"][w.name] = ser_world(w)

seen = set()
for o in scene.objects:
    if o.type in SUPPORTED and o.type != "EMPTY" and o.data is not None:
        key = (o.type, o.data.name)
        if key not in seen:
            seen.add(key)
            data["datas"].append(ser_data(o))
    data["objects"].append(ser_object(o, scene))

for c in bpy.data.collections:
    data["collections"].append({"name": c.name, "children": [ch.name for ch in c.children]})

sc = {
    "frame_start": scene.frame_start, "frame_end": scene.frame_end, "frame_current": scene.frame_current,
    "camera": scene.camera.name if scene.camera else None,
    "world": scene.world.name if scene.world else None,
    "render": props_simple(scene.render, {"filepath"}),
    "view_settings": props_simple(scene.view_settings),
    "display_settings": props_simple(scene.display_settings),
    "anim": ser_anim(scene),
}
for key in ("cycles", "eevee"):
    s = getattr(scene, key, None)
    if s is not None:
        sc[key] = props_simple(s)
if bpy.app.version < (5, 0, 0):
    if scene.use_nodes and scene.node_tree:
        sc["compositor"] = ser_tree(scene.node_tree)
else:
    warn("compositor not exported on Blender 5+")
data["scene"] = sc
data["meta"]["warnings"] = WARN

# ------------------------------------------------------------------ runtime (copied into the output file)
RUNTIME = r'''
import os
from mathutils import Matrix

IDMAP = {"OBJECT": "objects", "MATERIAL": "materials", "NODETREE": "node_groups", "COLLECTION": "collections",
         "IMAGE": "images", "LIGHT": "lights", "CAMERA": "cameras", "CURVE": "curves", "MESH": "meshes",
         "WORLD": "worlds", "FONT": "fonts", "SCENE": "scenes", "TEXT": "texts"}
DEFER_KINDS = {"OBJECT", "COLLECTION", "IMAGE"}

_built_groups = set()
_built_mats = set()
_datas = {}
_deferred = []


def warn(m):
    print("REBUILD WARN:", m)


def is_ref(v):
    return isinstance(v, dict) and "$ref" in v


def lookup(ref):
    kind, name = ref["$ref"]
    if kind == "NODETREE":
        build_group(name)
    elif kind == "MATERIAL":
        build_material(name)
    coll = getattr(bpy.data, IDMAP.get(kind, "_none_"), None)
    return coll.get(name) if coll is not None else None


def put_now(struct, key, v):
    target = lookup(v) if is_ref(v) else v
    if is_ref(v) and target is None:
        return
    setattr(struct, key, target)


def put(struct, key, v):
    try:
        if is_ref(v) and v["$ref"][0] in DEFER_KINDS:
            _deferred.append(lambda s=struct, k=key, x=v: put_now(s, k, x))
        else:
            put_now(struct, key, v)
    except Exception:
        pass


def put_item(obj, key, v):
    def go(o=obj, k=key, x=v):
        o[k] = lookup(x) if is_ref(x) else x
    try:
        if is_ref(v) and v["$ref"][0] in DEFER_KINDS:
            _deferred.append(go)
        else:
            go()
    except Exception:
        pass


def apply_props(struct, props, first=()):
    for k in first:
        if k in props:
            put(struct, k, props[k])
    for k, v in props.items():
        if k not in first:
            put(struct, k, v)


def build_interface(tree, items):
    for it in items:
        try:
            s = tree.interface.new_socket(name=it["name"], description=it.get("description", ""),
                                          in_out=it["in_out"], socket_type=it["socket_type"])
        except Exception as e:
            warn("interface socket %s: %s" % (it.get("name"), e))
            continue
        for k in ("subtype", "min_value", "max_value", "default_value", "hide_value"):
            if k in it:
                put(s, k, it[k])


def build_tree(tree, td):
    if td.get("interface"):
        build_interface(tree, td["interface"])
    tree.nodes.clear()
    nodes = {}
    for nd in td["nodes"]:
        try:
            n = tree.nodes.new(nd["bl_idname"])
        except Exception as e:
            warn("node %s (%s): %s" % (nd["name"], nd["bl_idname"], e))
            continue
        n.name = nd["name"]
        n.label = nd["label"]
        n.location = nd["location"]
        n.width = nd["width"]
        n.mute = nd["mute"]
        n.hide = nd["hide"]
        apply_props(n, nd["props"])
        rd = nd.get("ramp")
        if rd and getattr(n, "color_ramp", None) is not None:
            cr = n.color_ramp
            els = rd["elements"]
            try:
                cr.color_mode = rd["color_mode"]
                cr.interpolation = rd["interpolation"]
                cr.hue_interpolation = rd["hue"]
            except Exception:
                pass
            while len(cr.elements) < len(els):
                cr.elements.new(0.5)
            while len(cr.elements) > len(els):
                cr.elements.remove(cr.elements[-1])
            for e, ed in zip(cr.elements, els):
                e.position = ed["pos"]
                e.color = ed["color"]
        for i, v in nd["inputs"].items():
            if i < len(n.inputs):
                put(n.inputs[i], "default_value", v)
        for i, v in nd["outputs"].items():
            if i < len(n.outputs):
                put(n.outputs[i], "default_value", v)
        nodes[nd["name"]] = n
    for nd in td["nodes"]:
        if nd.get("parent") and nd["name"] in nodes and nd["parent"] in nodes:
            nodes[nd["name"]].parent = nodes[nd["parent"]]
    for l in td["links"]:
        try:
            tree.links.new(nodes[l["from"]].outputs[l["from_i"]], nodes[l["to"]].inputs[l["to_i"]])
        except Exception as e:
            warn("link %s -> %s: %s" % (l["from"], l["to"], e))


def build_group(name):
    if name in _built_groups:
        return
    _built_groups.add(name)
    gd = DATA["groups"].get(name)
    if gd is None or name in bpy.data.node_groups:
        return
    tree = bpy.data.node_groups.new(name, gd["bl_idname"])
    build_tree(tree, gd)


def build_material(name):
    if name in _built_mats:
        return
    _built_mats.add(name)
    md = DATA["materials"].get(name)
    if md is None or name in bpy.data.materials:
        return
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    apply_props(m, md["props"])
    if md["tree"]:
        build_tree(m.node_tree, md["tree"])


def build_world(name, wd):
    w = bpy.data.worlds.new(name)
    w.use_nodes = True
    try:
        w.color = wd["color"]
    except Exception:
        pass
    if wd.get("tree"):
        build_tree(w.node_tree, wd["tree"])


def build_spline(cu, sd):
    sp = cu.splines.new(sd["type"])
    pts = sd["points"]
    sp.use_cyclic_u = sd["cyclic"]
    sp.resolution_u = sd["resolution"]
    if sd["type"] == "BEZIER":
        sp.bezier_points.add(len(pts) - 1)
        for bp, pd in zip(sp.bezier_points, pts):
            bp.co = pd["co"]
            bp.handle_left_type = pd["tl"]
            bp.handle_right_type = pd["tr"]
            bp.handle_left = pd["hl"]
            bp.handle_right = pd["hr"]
            bp.radius = pd["radius"]
            bp.tilt = pd["tilt"]
    else:
        sp.points.add(len(pts) - 1)
        for pt, pd in zip(sp.points, pts):
            pt.co = pd["co"]
            pt.radius = pd["radius"]
            pt.tilt = pd["tilt"]
        if sd["type"] == "NURBS":
            sp.order_u = sd.get("order_u", 4)
            sp.use_endpoint_u = sd.get("use_endpoint_u", False)


def build_data(dd):
    t = dd["type"]
    name = dd["name"]
    if t == "MESH":
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in dd["verts"]], [tuple(e) for e in dd.get("edges", [])],
                       [tuple(f) for f in dd["faces"]])
        me.update()
        for p, mi, sm in zip(me.polygons, dd["mat_index"], dd["smooth"]):
            p.material_index = mi
            p.use_smooth = sm
        block = me
    elif t in ("FONT", "CURVE"):
        cu = bpy.data.curves.new(name, t)
        apply_props(cu, dd["props"], first=("dimensions",))
        for sd in dd.get("splines", []):
            build_spline(cu, sd)
        for fd in dd.get("fonts", []):
            fp = bpy.path.abspath(fd["filepath"])
            if os.path.exists(fp):
                setattr(cu, fd["slot"], bpy.data.fonts.load(fp))
            else:
                warn("font file not found: %s (using default font)" % fd["filepath"])
        block = cu
    elif t == "LIGHT":
        block = bpy.data.lights.new(name, dd["light_type"])
        apply_props(block, dd["props"])
    elif t == "CAMERA":
        block = bpy.data.cameras.new(name)
        apply_props(block, dd["props"])
        apply_props(block.dof, dd.get("dof", {}))
    else:
        return
    for mname in dd.get("materials", []):
        block.materials.append(bpy.data.materials.get(mname) if mname else None)
    _datas[(t, name)] = block


def build_collections(scene):
    cols = {}
    for cd in DATA["collections"]:
        cols[cd["name"]] = bpy.data.collections.new(cd["name"])
    for cd in DATA["collections"]:
        for ch in cd["children"]:
            if ch in cols:
                cols[cd["name"]].children.link(cols[ch])
    for cn in DATA["master_children"]:
        if cn in cols:
            scene.collection.children.link(cols[cn])
    return cols


def build_objects(scene, cols):
    objs = {}
    for od in DATA["objects"]:
        block = _datas.get((od["type"], od["data"])) if od["data"] else None
        o = bpy.data.objects.new(od["name"], block)
        o.rotation_mode = od["rot_mode"]
        o.location = od["loc"]
        o.rotation_euler = od["rot_euler"]
        o.rotation_quaternion = od["rot_quat"]
        o.scale = od["scale"]
        for k, v in od["flags"].items():
            put(o, k, v)
        if od["type"] == "EMPTY":
            apply_props(o, od.get("empty", {}))
        linked = False
        for cn in od["collections"]:
            target = scene.collection if cn == "$master" else cols.get(cn)
            if target is not None:
                target.objects.link(o)
                linked = True
        if not linked:
            scene.collection.objects.link(o)
        objs[o.name] = o
    return objs


def build_anim(idb, a):
    if not a or idb is None:
        return
    ad = idb.animation_data_create()
    if a.get("fcurves"):
        try:
            act = bpy.data.actions.new(idb.name + "Action")
            ad.action = act
            for fd in a["fcurves"]:
                fc = act.fcurves.new(fd["data_path"], index=fd["array_index"])
                fc.extrapolation = fd["extrapolation"]
                fc.keyframe_points.add(len(fd["keys"]))
                for kp, kd in zip(fc.keyframe_points, fd["keys"]):
                    kp.co = kd["co"]
                    kp.interpolation = kd["interp"]
                    kp.handle_left_type = kd["tl"]
                    kp.handle_right_type = kd["tr"]
                    kp.handle_left = kd["hl"]
                    kp.handle_right = kd["hr"]
                for md in fd.get("modifiers", []):
                    fm = fc.modifiers.new(md["type"])
                    apply_props(fm, md["props"])
                fc.update()
        except Exception as e:
            warn("keyframes on %s not rebuilt: %s" % (idb.name, e))
    for dd in a.get("drivers", []):
        fc = None
        try:
            fc = idb.driver_add(dd["data_path"], dd["array_index"])
        except Exception:
            try:
                res = idb.driver_add(dd["data_path"])
                fc = res[dd["array_index"]] if isinstance(res, list) else res
            except Exception as e:
                warn("driver %s on %s: %s" % (dd["data_path"], idb.name, e))
                continue
        drv = fc.driver
        drv.type = dd["type"]
        for vd in dd["vars"]:
            var = drv.variables.new()
            var.name = vd["name"]
            var.type = vd["type"]
            for tg, td in zip(var.targets, vd["targets"]):
                try:
                    tg.id_type = td["id_type"]
                    if td["id"]:
                        tg.id = lookup(td["id"])
                    tg.data_path = td["data_path"]
                    if var.type == "TRANSFORMS":
                        tg.transform_type = td["transform_type"]
                        tg.transform_space = td["transform_space"]
                        tg.rotation_mode = td["rotation_mode"]
                except Exception as e:
                    warn("driver variable %s: %s" % (vd["name"], e))
        drv.expression = dd["expression"]
        drv.use_self = dd["use_self"]


def clean():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.collections, bpy.data.meshes, bpy.data.curves, bpy.data.lights,
                 bpy.data.cameras, bpy.data.materials, bpy.data.node_groups, bpy.data.worlds):
        for b in list(coll):
            coll.remove(b)


def apply_scene(scene, sd, objs):
    for key in ("render", "cycles", "eevee", "view_settings", "display_settings"):
        struct = getattr(scene, key, None)
        if struct is not None and key in sd:
            apply_props(struct, sd[key], first=("engine", "view_transform"))
    scene.frame_start = sd["frame_start"]
    scene.frame_end = sd["frame_end"]
    scene.frame_current = sd["frame_current"]
    if sd.get("camera") in objs:
        scene.camera = objs[sd["camera"]]
    if sd.get("world"):
        scene.world = bpy.data.worlds.get(sd["world"])
    if sd.get("compositor"):
        try:
            scene.use_nodes = True
            build_tree(scene.node_tree, sd["compositor"])
        except Exception as e:
            warn("compositor not rebuilt: %s" % e)
    build_anim(scene, sd.get("anim"))


def build():
    scene = bpy.context.scene
    if CLEAN_START:
        clean()
    for name in DATA["groups"]:
        build_group(name)
    for name in DATA["materials"]:
        build_material(name)
    for name, wd in DATA["worlds"].items():
        build_world(name, wd)
    for dd in DATA["datas"]:
        build_data(dd)
    cols = build_collections(scene)
    objs = build_objects(scene, cols)

    for od in DATA["objects"]:
        o = objs[od["name"]]
        if od.get("parent") in objs:
            o.parent = objs[od["parent"]]
            o.parent_type = od["parent_type"]
            o.matrix_parent_inverse = Matrix(od["parent_inverse"])
        for md in od["modifiers"]:
            m = o.modifiers.new(md["name"], md["type"])
            if m is None:
                continue
            m.name = md["name"]
            if md["type"] == "NODES":
                if md.get("node_group"):
                    m.node_group = lookup(md["node_group"])
                for k, v in md.get("inputs", {}).items():
                    put_item(m, k, v)
            apply_props(m, {k: v for k, v in md["props"].items() if k != "node_group"})
        for cd in od["constraints"]:
            c = o.constraints.new(cd["type"])
            c.name = cd["name"]
            apply_props(c, cd["props"])

    for fn in _deferred:
        try:
            fn()
        except Exception:
            pass

    for od in DATA["objects"]:
        build_anim(objs[od["name"]], od.get("anim"))
    for dd in DATA["datas"]:
        build_anim(_datas.get((dd["type"], dd["name"])), dd.get("anim"))
    for name, md in DATA["materials"].items():
        m = bpy.data.materials.get(name)
        if m is not None and m.node_tree is not None:
            build_anim(m.node_tree, md.get("anim"))
    for name, wd in DATA["worlds"].items():
        w = bpy.data.worlds.get(name)
        if w is not None and w.node_tree is not None:
            build_anim(w.node_tree, wd.get("anim"))
    for name, gd in DATA["groups"].items():
        build_anim(bpy.data.node_groups.get(name), gd.get("anim"))

    apply_scene(scene, DATA["scene"], objs)
    print("Scene rebuilt: %d objects, %d materials, %d node groups." % (
        len(DATA["objects"]), len(DATA["materials"]), len(DATA["groups"])))
'''

# ------------------------------------------------------------------ write the output file
base = bpy.path.abspath("//") if bpy.data.filepath else os.path.expanduser("~")
path = os.path.join(base, "AGWS-scene-rebuild.py")

header = (
    "# Auto-generated by export_scene_as_code.py (Blender %s)\n"
    "# Source file: %s\n"
    "# HOW TO USE: open a NEW empty Blender file, load this script in the Scripting tab, Run Script.\n"
    "# CLEAN_START deletes all existing objects/materials/etc. in the open file before building.\n"
    "import bpy\n\n"
    "CLEAN_START = True\n\n"
    "DATA = "
) % (data["meta"]["blender"], data["meta"]["source"])

with open(path, "w", encoding="utf-8") as fh:
    fh.write(header)
    fh.write(pprint.pformat(data, width=110, compact=True, sort_dicts=False))
    fh.write("\n\n")
    fh.write(RUNTIME)
    fh.write("\n\nbuild()\n")

print("Scene exported as code:", path)
print("%d warning(s)." % len(WARN))
