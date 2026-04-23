import bpy, math
from mathutils import Vector
scene = bpy.context.scene
cam = bpy.data.objects['Camera']
arm = bpy.data.objects['CMU compliant skeleton']
mesh = bpy.data.objects['asMesh']
cam.rotation_mode = 'XYZ'
cam.rotation_euler = tuple(math.radians(v) for v in (63.435, 0.0, 45.0))
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 42.999996185302734
arm.rotation_mode = 'XYZ'
arm.rotation_euler.z = 0.0
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
eval_obj = mesh.evaluated_get(deps)
eval_mesh = eval_obj.to_mesh()
cam_inv = cam.matrix_world.inverted()
xs=[]; ys=[]
for v in eval_mesh.vertices:
    local = cam_inv @ (eval_obj.matrix_world @ v.co)
    xs.append(local.x)
    ys.append(local.y)
print('bbox_local_width', max(xs)-min(xs))
print('bbox_local_height', max(ys)-min(ys))
print('center_local', (min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
print('aspect', scene.render.resolution_x / scene.render.resolution_y)
eval_obj.to_mesh_clear()
