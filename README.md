# 会议录音机 (Meeting Recorder)

常驻 Windows 系统托盘（右下角）的轻量会议录音工具。可同时录制**系统音频（扬声器输出）**和**麦克风**，混音保存为单个 WAV 文件。

## 功能

- 启动后最小化到系统托盘，后台常驻。
- **左键单击**托盘图标：开始 / 停止录音（图标变红表示录音中）。
- **右键菜单**：开始/停止录音、打开录音文件夹、退出。
- 同时捕获系统音频 + 麦克风，自动混音并防削波。
- 录音保存到 `C:\Users\<你>\Meeting Recordings\meeting_<时间戳>.wav`。

## 直接使用（exe）

打包好的可执行文件在 `dist\MeetingRecorder.exe`，双击即可运行，无需安装 Python。

## 从源码运行

依赖管理使用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync          # 安装依赖
uv run python main.py
```

## 重新打包 exe

```bash
uv run pyinstaller --noconfirm --onefile --windowed \
    --name MeetingRecorder --icon icon.ico --add-data "icon.ico;." \
    --collect-all soundcard main.py
```

生成的文件位于 `dist\MeetingRecorder.exe`（单文件，约 30 MB）。

## 图标

- 源文件为 `icon.svg`（麦克风），用 `make_icon.py` 渲染成多尺寸 `icon.ico`：

  ```bash
  uv run python make_icon.py
  ```

- `icon.ico` 既作为 exe 图标（`--icon`），也在运行时随包打入用作托盘图标；
  录音时托盘图标右下角会叠加红点表示「录音中」。

## 技术说明

- **录音**：`soundcard` 库，通过 Windows WASAPI loopback 抓取默认扬声器输出，同时录制默认麦克风；两路各用一个线程，停止时按较短长度对齐并相加混音。
- **托盘**：`pystray` + `Pillow`，底图为麦克风图标，录音时叠加红点。
- 输出为 48 kHz、双声道、16-bit PCM WAV。

## 已知限制 / 可扩展方向

- 录制的是**默认**扬声器与麦克风；切换设备需在系统声音设置中调整。
- 全程音频缓存在内存中，超长会议（数小时）会占用较多内存——如有需要可改为边录边写盘。
- 暂未提供 MP3 压缩、设备选择菜单、开机自启动等功能，可按需扩展。
