# Gemini 交接说明：男忍者紧身服五方向一致性

## 目标

请继续处理这个任务：

- 目标角色：`adult male`
- 目标服装：`忍者紧身服 / ninja bodysuit`
- 目标输出：`S / SE / E / NE / N` 五方向
- 目标要求：
  - 同一套衣服在不同方向上尽量一致
  - 白底或近白底
  - 不要脏背景
  - 不要高开衩泳装感
  - 不要裸露
  - 可作为 RPG 换装底图参考

## 很重要

这次任务必须“多测、多看图”，不要只看日志或参数。

请按这个节奏工作：

1. 先只跑 `1-3` 张代表方向，例如 `S / E / N`
2. 每次都实际打开图片看结果
3. 不满意就先修参考图或参数，不要直接整批跑 5 张
4. 只有小样本通过后，再补全 `SE / NE`

## 环境信息

- 项目根目录：`D:\Godot\comfyui`
- ComfyUI 根目录：`C:\Users\12536\Documents\ComfyUI`
- ComfyUI API 端口：`http://127.0.0.1:8000`
- Blender 场景：`makehuman.blend`

## 当前可用文件

### 主要 workflow

- 通用五方向 workflow：
  - `00_workflows/char_5direction_v1.json`
- 两阶段相关：
  - `00_workflows/char_ninja_master_v1.json`
  - `00_workflows/char_ninja_lock_v1.json`
  - `00_workflows/char_ninja_lock_v2.json`

### 脚本

- Blender 五方向辅助图：
  - `scripts/blender_auto_render.py`
- ComfyUI 批处理：
  - `scripts/comfyui_batch.py`
- 准备 IPAdapter 参考图：
  - `scripts/prepare_ipadapter_reference.py`
- 用 Blender alpha 清理生成图背景：
  - `scripts/apply_character_mask.py`

### 辅助图目录

- `02_blender/renders/beauty`
- `02_blender/renders/depth`
- `02_blender/renders/pose`
- `02_blender/renders/normal`

目前已有 `male_normal_{S,SE,E,NE,N}.png` 的辅助图。

### 当前参考图

- 原始主参考：
  - `04_comfyui_output/raw/male_ninja_master_S.png`
- 清底并聚焦后的参考：
  - `03_comfyui_input/male_ninja_master_reference_focus.png`

## 当前结果判断

### 完全失败，不要继续沿用结果

这些图是失败样例：

- `04_comfyui_output/raw/male_ninja_clean_S.png`
- `04_comfyui_output/raw/male_ninja_clean_E.png`
- `04_comfyui_output/raw/male_ninja_clean_N.png`

问题：

- 基本塌成脏纹理
- 人物信息丢失严重
- 不具备继续生产价值

### 可看但不可直接定稿

这 3 张是目前“最接近能用”的结果：

- `04_comfyui_output/raw/male_ninja_v2r_S.png`
- `04_comfyui_output/raw/male_ninja_v2r_E.png`
- `04_comfyui_output/raw/male_ninja_v2r_N.png`

这些图的优点：

- 背景已经清干净
- 人物没有塌掉
- 前视 `S` 的衣服方向基本对
- 比最初那批结果稳定很多

这些图的缺点：

- `E / N` 后背和臀部区域仍然有“高开衩连体衣/泳装感”
- 还不够像“全覆盖的男忍者紧身服”
- 不能算生产级定稿

### 失败根因

目前的根因基本明确：

1. 第一阶段的 `master` 参考图本身就不够稳定
2. `IPAdapter` 太强时会把参考图的脏背景和错误服装轮廓一起学进去
3. 只靠 prompt 很难把“后背/裆部必须全覆盖”稳定锁住
4. 第二阶段只能“跟着参考走”，如果参考本身服装设计有问题，后面只会放大问题

## 当前建议路线

最务实的路线不是继续狂调第二阶段，而是：

1. 先得到一张真正正确的 `master` 参考图
2. 这张图必须满足：
   - 白底
   - 近白底无纹理
   - 男性忍者紧身服
   - 头套、面罩、手套、鞋、躯干、臀部、裆部都明确覆盖
   - 不要泳装感
   - 不要高开衩
3. 再把这张图送进 `lock_v2`
4. 只先重跑 `S / E / N`
5. 看图确认后再补 `SE / NE`

## 建议你优先做的事情

### 方案 A：先修 master 参考图

这是最推荐的。

建议做法：

- 不要直接用现在的 `male_ninja_master_S.png`
- 重新生成或手修一张更像“全覆盖忍者紧身服”的 master 图
- 尤其要修正：
  - 臀部覆盖
  - 裆部覆盖
  - 后背线条
  - 腰部结构

如果你能手动修图，修完后再喂第二阶段，成功率会高很多。

### 方案 B：继续小样本调第二阶段

只在你不想先修 master 时采用。

建议：

- 仍然使用 `char_ninja_lock_v2.json`
- 只测试 `S / E / N`
- 每轮都看图
- 如果后背继续泳装化，不要继续整批跑

## 当前推荐命令

### 1. 生成聚焦参考图

```powershell
python scripts/prepare_ipadapter_reference.py ^
  --source 04_comfyui_output/raw/male_ninja_master_S.png ^
  --mask-image 02_blender/renders/beauty/male_normal_S.png ^
  --output 03_comfyui_input/male_ninja_master_reference_focus.png
```

### 2. 用 `lock_v2` 只跑 `S / E / N`

```powershell
python scripts/comfyui_batch.py ^
  --workflow 00_workflows/char_ninja_lock_v2.json ^
  --body-type male_normal ^
  --output-prefix male_ninja_try ^
  --directions S E N ^
  --reference-image 03_comfyui_input/male_ninja_master_reference_focus.png ^
  --comfyui-root C:\Users\12536\Documents\ComfyUI
```

### 3. 对生成结果硬清底

```powershell
python scripts/apply_character_mask.py ^
  --source 04_comfyui_output/raw/male_ninja_try_S.png ^
  --mask-image 02_blender/renders/beauty/male_normal_S.png ^
  --output 04_comfyui_output/raw/male_ninja_try_clean_S.png
```

`E / N` 同理，把 `mask-image` 换成对应方向的 `beauty` 图。

## 验收标准

请至少满足下面这些再算“可继续”：

- `S / E / N` 三张都有人物完整轮廓
- 背景干净
- 三张明显是同一套衣服
- 头套、面罩、手套、鞋型基本一致
- 后背和臀部不是泳装感
- 裆部不是裸露或高开衩

如果达不到这些条件，请不要直接扩到五方向。

## 当前提交记录

- 两阶段基础流程：
  - `611ba32 feat: add two-stage ninja outfit workflows`
- 稳定参考输出的补丁：
  - `d99b1f9 fix: stabilize ninja reference outputs`

## 结论

当前仓库里最有价值的不是“已经成功出完图”，而是：

- 已经验证哪些路线会炸
- 已经补了参考图准备脚本
- 已经补了生成结果清底脚本
- 已经有一版相对更稳的 `lock_v2`

下一步最值得做的是：先拿到一张真正正确的 `master` 忍者服参考图，再继续锁方向。
