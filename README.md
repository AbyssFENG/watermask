# 光影水印 Photo Watermark Studio（Windows 桌面版）

本地照片水印工具。程序在本机处理图片，不会把照片上传到网络。

当前界面使用 **PySide6**。图片读取、EXIF 和水印合成仍由 **Pillow** 完成。原来的 Tkinter 程序保留在 `photo_watermark_studio.py`，对照备份在 `backup/tkinter_mvp_2026-10-28.py`。

## 当前功能

- 导入多张照片，或递归导入整个文件夹；可移除选中照片或清空列表。
- 读取照片中实际存在的 EXIF：相机品牌/型号、镜头、焦距、光圈、快门、ISO、拍摄时间、GPS。没有这些字段时不会编造参数。
- 三种模板：
  - **经典底栏**：照片下方增加一条浅色、深色或蓝色信息栏。
  - **极简叠加**：在照片底部叠加半透明信息条。
  - **卡片相框**：在照片外增加边距、圆角、阴影和参数文字。
- 可设置署名、补充说明、Logo（建议透明 PNG）、显示哪些字段、水印大小和 JPG 质量。
- 选择照片后生成预览。预览按窗口缩放；导出时会重新读取原图渲染，不会把预览小图直接存盘。
- 支持保存当前图片，以及后台批量导出。某一张失败时，其余照片继续处理，可取消尚未开始的后续任务。
- 原图不会被覆盖。默认文件名为 `原文件名_watermark.jpg`。输出到其他目录且文件重名时，使用 `_2`、`_3` 编号。
- 导出目录和水印选项保存在本机 JSON 中，不保存照片本身。

## Windows 运行方法

使用 conda 环境 **watermask**（本机为 Python 3.12）。

1. 双击 `run_windows.bat`。脚本会用 `watermask` 安装依赖并启动程序。
2. 也可以在本目录手动执行：

```powershell
conda activate watermask
python -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
Push-Location src
python -m photo_watermark_studio.main
Pop-Location
```

需要先进入 `src` 再启动，是因为项目根目录还留着同名的旧版 `photo_watermark_studio.py`。

只想对照旧界面时，在 `watermask` 中执行：

```powershell
conda activate watermask
python photo_watermark_studio.py
```

## 打包成 EXE（可选）

双击 `build_exe.bat`。脚本使用 PyInstaller 生成目录版程序，输出在：

`dist\PhotoWatermarkStudio\PhotoWatermarkStudio.exe`

请在一台没有开发环境的 Windows 上再确认启动、导入、预览和导出。目录版确认可用之前，不使用单文件打包。

## 关于 EXIF

程序只读取文件里仍然存在的元数据。社交媒体下载图、截图，以及某些软件导出的照片，可能已经没有 EXIF。此时可以填写“自定义说明”。

支持 JPG/JPEG、PNG、WEBP、TIF/TIFF、BMP。相机 RAW（NEF、CR3、ARW 等）暂不直接处理。

## 项目结构

- `src/photo_watermark_studio/main.py`：PySide6 入口。
- `src/photo_watermark_studio/app_window.py`：主窗口。
- `src/photo_watermark_studio/core/`：EXIF、水印渲染、导出和设置保存，不依赖界面库。
- `src/photo_watermark_studio/widgets/`：照片列表、预览和设置面板。
- `src/photo_watermark_studio/workers/`：预览与批量导出的后台任务。
- `tests/`：核心逻辑和离屏界面测试。
- `photo_watermark_studio.py`：迁移前的 Tkinter 版本。
