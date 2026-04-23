import bpy
cam = bpy.data.objects['Camera']
print('cam_scale', tuple(cam.scale))
print('cam_location', tuple(cam.location))
print('cam_rotation', tuple(cam.rotation_euler))
