import bpy
from pathlib import Path
import math

scene = bpy.context.scene
cam = bpy.data.objects['Camera']
arm = bpy.data.objects['CMU compliant skeleton']
meshes = [o for o in arm.children_recursive if o.type == 'MESH']
print([m.name for m in meshes])
