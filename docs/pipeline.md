# 流程文档

## 1. 总体流程

## 2. MakeHuman 阶段

## 3. Blender 阶段

Blender 阶段负责把角色几何投影成下游流程需要的 depth / normal / beauty / pose
图。两条独立 track：

### 3.1 `male_normal` 正式玩家角色 track

- 场景来源：`makehuman.blend`
- 渲染脚本：[`scripts/blender_auto_render.py`](../scripts/blender_auto_render.py)
- 输出目录：
  - `02_blender/renders/beauty/`
  - `02_blender/renders/depth/` (`male_normal_*.png`)
  - `02_blender/renders/normal/`
  - `02_blender/renders/pose/`
- 方向：默认 `S, SE, SW, E, NE`；`N` 与 `E` 在当前正式玩家集合里镜像等价，
  默认只保留 `E`
- 运行：

  ```
  blender --background makehuman.blend --python scripts/blender_auto_render.py -- \
      --body-type male_normal --model-object CharacterRoot
  ```

### 3.2 `female_age{0-8}` 按年龄排序的女性参考集 track

- 输入：[`fbx/n0.fbx` … `fbx/n8.fbx`](../fbx)（按年龄从小到大排序）
- 渲染脚本：[`scripts/blender_fbx_depth.py`](../scripts/blender_fbx_depth.py)
  + [`scripts/compose_5views_depth.py`](../scripts/compose_5views_depth.py)
- 输出目录：`02_blender/renders/depth/`（与男性 canonical 共用同一目录，但
  文件前缀区分）
- 输出文件：
  - `female_age{0-8}_S.png`、`_SE.png`、`_SW.png`、`_E.png`、`_NE.png`
    单方向深度
  - `female_age{0-8}_5views_depth.png` 五视图拼贴，左到右顺序
    `SW, S, SE, E, NE`（从纯正面到纯背面的旋转）
- 相机设置与 `blender_auto_render.py` 完全一致，所以两条 track 的深度比例
  可以直接比较
- 这条 track 是**参考学习集**，不进入正式玩家 pipeline。不要当成 canonical
  player 资源删除或替换男性集合
- 运行：

  ```
  blender --background --python scripts/blender_fbx_depth.py -- \
      --fbx-dir D:/Godot/comfyui/fbx \
      --out-dir D:/Godot/comfyui/02_blender/renders/depth \
      --pattern "n*.fbx" \
      --directions "S,SE,SW,E,NE" \
      --stem-format "female_age{index}"

  python scripts/compose_5views_depth.py \
      --depth-dir D:/Godot/comfyui/02_blender/renders/depth \
      --stems female_age0,female_age1,female_age2,female_age3,female_age4,female_age5,female_age6,female_age7,female_age8
  ```

### 3.3 目录守则

- `02_blender/renders/depth/README.md` 描述该目录收纳的两个 track，任何
  新加 body type 必须更新它
- 不要把 GPT-image 或 beauty 推导出来的深度图塞进 `depth/`，那里只能放
  Blender 几何投影
- 不要修改 `scripts/blender_auto_render.py` 里的相机默认参数
  (`DEFAULT_CAMERA_ROTATION`、`DEFAULT_TARGET_*_FILL`)；FBX track 的
  `scripts/blender_fbx_depth.py` 也沿用同一组常数，两者必须保持一致，否则
  两个集合之间的深度尺度会失配

## 4. ComfyUI 阶段

### 4.1 ComfyUI HTTP 批量

- 脚本：[`scripts/comfyui_batch.py`](../scripts/comfyui_batch.py)
- 通过 workflow JSON 驱动本地 ComfyUI，把 depth/normal/pose 图喂成彩色渲染
- workflow 模板在 [`00_workflows/`](../00_workflows)

### 4.2 GPT Image 图生图（OpenAI 云侧）

- 脚本：[`scripts/gpt_image_edit.py`](../scripts/gpt_image_edit.py)
- 用途：把 depth/normal 参考图（比如
  `02_blender/renders/depth/female_age{0-8}_5views_depth.png`）扔给 OpenAI
  `gpt-image-1` / `gpt-image-2` 做 img2img，获得上色/风格化角色表
- 前置条件：环境变量 `OPENAI_API_KEY`（在 PowerShell 里 `setx OPENAI_API_KEY "sk-..."`，
  bash 里 `export OPENAI_API_KEY=sk-...`）
- 走国内中转：再加 `OPENAI_BASE_URL`（例 `https://timesniper.club/v1`），或单次调用用
  `--base-url` 覆盖。中转站必须支持 OpenAI 原生 `/images/edits` 路径
- 输出建议写入 `04_comfyui_output/raw/`，命名沿用 `{stem}_gptimage.png` 的
  惯例，和 `male_normal_5views_player_depth_gptimage.png` 保持一致
- 单次调用示例：

  ```
  python scripts/gpt_image_edit.py \
      --input 02_blender/renders/depth/female_age4_5views_depth.png \
      --prompt "anime-style five-view character sheet, young woman, soft lighting" \
      --output 04_comfyui_output/raw/female_age4_5views_gptimage.png \
      --size auto --quality high --background transparent
  ```

- 多参考图（depth + style ref）：`--input` 可以重复
- `--prompt` 支持 `@path/to/prompt.txt` 从文件读
- 模型默认 `gpt-image-1`；如果账号可用 `gpt-image-2`，显式传 `--model gpt-image-2`
- 注意：每次调用都在烧 OpenAI 配额，批量循环前先确认单价；脚本不做缓存
- 已知坑：`gpt-image-2` 不接受 `--background transparent`（服务端返回
  `image_generation_user_error`），默认 `auto` 或 `opaque` 即可，透明背景
  靠 prompt 指定

### 4.3 GPT Image 批量（9 个 5 视图）

- 脚本：[`scripts/gpt_image_batch_5views.py`](../scripts/gpt_image_batch_5views.py)
- 提示词模板：[`prompts/isometric_base_5views.md`](../prompts/isometric_base_5views.md)
  （**女性人体**等距 2.5D RPG 基底，动漫手绘风，纯白背景，不要头发，
  禁止戏剧灯光/颗粒/纹理/棕褐色晕染。性别必须写死在 prompt 里 —
  `female_age1/2/4/8` 在 quality `medium` 实测会被 gpt-image-2 出成男性，
  见 `prompts/README.md` 注释）
- 默认吃 `02_blender/renders/depth/female_age*_5views_depth.png`，输出到
  `04_comfyui_output/raw/female_age{N}_5views_gptimage.png`，skip-existing
  幂等
- 先单张冒烟（`--limit 1 --quality low`）再跑全量：

  ```
  python scripts/gpt_image_batch_5views.py --limit 1 --quality low --dry-run
  python scripts/gpt_image_batch_5views.py --limit 1 --quality low
  python scripts/gpt_image_batch_5views.py --quality medium
  ```

- 换提示词就用 `--prompt-file prompts/其它.md`；新增提示词文件要遵守
  [`prompts/README.md`](../prompts/README.md) 的"纯正文，无 front-matter"规则
- 如果走中转：`OPENAI_BASE_URL` 环境变量已被子脚本读取，无需额外参数
- **不想守着本机？** 同一份脚本在 GitHub Actions 跑得起来，见
  [`.github/workflows/gpt_image_batch.yml`](../.github/workflows/gpt_image_batch.yml)：
  - Actions 页一键 `Run workflow`，跑完产物作 artifact 下载
  - 输入参数有 `pattern` / `quality` / `max_retries` / `timeout` / `force`，
    比如只补 `female_age[1248]` 就把 pattern 改成
    `female_age[1248]_5views_depth.png`
  - 需要在 repo Settings 里设两个 Secret：`OPENAI_API_KEY` 和
    `OPENAI_BASE_URL`（中转站 URL；用官方 OpenAI 的话留空）
  - 实测：GitHub runner 在美/欧区，连国内中转站延迟可能反而比家里宽带糟，
    第一次跑先小批量（`pattern` 限一张）确认链路通再放大
- **Moderation 是概率事件**，同一输入+提示词可能这次被拦下次放行。
  `gpt_image_edit.py` 内置重试循环（默认 `--max-retries 10`，`--retry-delay 3`
  秒，rate-limit 自动拉长 4×，所有延迟带 ±25% 抖动），只对以下错误类别重试：
  - `moderation_blocked` / `content_policy_violation`（probabilistic 命中）
  - `RateLimitError`
  - `APITimeoutError` / `APIConnectionError`
  - `InternalServerError` (5xx)

  其他错误（鉴权失败、配额耗尽、无效参数等）**不重试**，直接抛出，避免
  在必然失败的请求上烧钱。批量脚本把 `--max-retries` / `--retry-delay` 原样
  透传给单次调用

### 4.4 GPT Image 产物归档守则

- GPT Image 出来的 PNG 属于"生成物"，**不允许**回灌到
  [`02_blender/renders/depth/`](../02_blender/renders/depth/) 或其他 Blender 几何投影目录
- 现存的 `male_normal_5views_player_depth_gptimage.png` 是历史遗留，保留参考但
  不做新增样板
- 新生成物放 `04_comfyui_output/raw/`，后续 Photoshop 清理后升级到
  `05_ps_wip/`

## 5. Photoshop 阶段

## 6. Spine 阶段

## 7. Godot 集成阶段

## 8. 版本管理与交付
