# 光影水印 Photo Watermark Studio 3.0（Windows 桌面版）

本地照片元数据水印工具。程序在本机处理图片，不会把照片上传到网络。

当前界面使用 **PySide6**。图片读取、EXIF 和水印合成由 **Pillow** 完成。原来的 Tkinter 程序保留在上级目录 [`../photo_watermark_studio.py`](../photo_watermark_studio.py)，对照备份在 `backup/tkinter_mvp_2026-10-28.py`。

## 3.0 当前能力

- 三栏工作台：左侧缩略图素材区、中间画布预览、右侧分组属性面板。
- 导入多张照片或文件夹；支持拖入素材区；搜索与排序；网格/列表视图。
- 照片状态：待处理 / 已编辑 / 导出中 / 已完成 / 失败。
- 内置模板：经典底栏、极简叠加、卡片相框、纯文字中下；另有「自定义」（可选底版并拖动位置）。
- 用户模板：本机保存 / 应用 / 重命名 / 删除（导入导出后续再做）。
- 配色：浅色、深色、蓝色、高斯模糊。
- 画布：适应窗口、缩放、原图对比；自定义模式下可拖动水印；点击文字改文案、字号、字体、加粗与透明度。
- 撤销/重做（模板级样式变更）。
- 单张覆盖按照片路径保存；素材区标记「已编辑」。
- 导出格式：JPG / PNG / WEBP / TIFF（文件名默认 `{原名}_watermark{扩展名}`；默认不覆盖原图；重名自动编号；可选覆盖策略需确认）。
- 导出选项：JPG 质量、PNG 压缩等级、WEBP 质量；可选保留 EXIF 与 ICC 色彩配置（默认开启）。
- 单张与批量导出均在后台执行，显示进度，可取消后续任务；单张失败不中断其余任务。

## Windows 运行方法

使用 conda 环境 **watermask**（本机为 Python 3.12）。

1. 双击 `run_windows.bat`。
2. 或手动：

```powershell
conda activate watermask
python -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
python -m photo_watermark_studio.main
```

## 打包成 EXE（可选）

双击 `build_exe.bat`。输出在：

`dist\PhotoWatermarkStudio\PhotoWatermarkStudio.exe`

## 关于 EXIF

程序只读取文件里仍然存在的元数据。缺失字段不会伪造，也不会串用上一张照片的参数。

支持 JPG/JPEG、PNG、WEBP、TIF/TIFF、BMP。相机 RAW 暂不直接处理。

导出时可选择是否把原图 EXIF、ICC 写回输出文件（方向已校正的图片会将 Orientation 标为 1）。

## 项目结构

- `src/photo_watermark_studio/main.py`：入口
- `src/photo_watermark_studio/app_window.py`：主窗口
- `src/photo_watermark_studio/core/`：文档模型、坐标映射、渲染、导出、会话
- `src/photo_watermark_studio/ui/`：画布与可交互图元
- `src/photo_watermark_studio/widgets/`：素材区、属性面板
- `src/photo_watermark_studio/workers/`：预览、缩略图、导出（单张与批量）
- `tests/`：核心与离屏界面测试
- [`../photo_watermark_studio.py`](../photo_watermark_studio.py)：旧版 Tkinter 单文件（对照用）
- [`../Photo_Watermark_Studio_UI_2.0_改版设计.md`](../Photo_Watermark_Studio_UI_2.0_改版设计.md)：改版设计说明
- [`../MIGRATION_TKINTER_TO_PYSIDE6.md`](../MIGRATION_TKINTER_TO_PYSIDE6.md)：Tk → PySide6 迁移记录（已完成）
