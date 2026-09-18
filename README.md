# RYCOM 串口调试工具（PySide6 重构版）

基于[原 RYCOM（Qt/C++）项目](https://github.com/rymcu/RYCOM)，使用 PySide6 重新实现的**纯串口调试**工具，
去除了原版的 STM32/ESP32 下载、Ymodem 文件传输、局域网状态 HTTP 服务，
仅保留核心串口收发相关功能

## 动机
我很喜欢RYCOM，简洁好用，用了好几年了，但随着我不再使用Windows，而是使用Linux作为电脑唯一的操作系统后，我发现RYCOM并未提供Linux版本。由于原版项目基于Qt/C++，我并不是很熟悉，所以我选择了我更熟悉的Python，况且pyinstaller打包也很方便，于是就有了这个Pyside6重构版本，意在Linux上还原原版RYCOM的使用体验

感谢 **国模一哥** 和 **大肥鱼** 承担本项目的主要编码工作


## 功能

- 串口扫描、参数（波特率/数据位/校验/停止位，流控固定 None）设置与打开/关闭
- 文本 / HEX 收发显示，可切换（收发使用系统编码）
- 接收区：显示时间戳、停止显示（缓存后恢复一次性输出）、清空、保存为文件
- 发送区：HEX 发送、自动加换行（`\r\n`）、清空、从文件读入
- 多行发送区（默认隐藏，勾选"多行发送"后显示，每行一帧，可勾选逐条发送）
- 周期发送 / 多行循环发送（共用定时器，互斥，周期 ms 可设）
- 串口状态指示灯（打开变红，关闭变黑）
- 收发字节计数与速率（KB/s）实时统计，可清零
- 参数记忆（关闭时写入 `config.ini`，下次自动恢复）


## 文件结构

- `main.py`：单文件，包含串口封装、端口扫描、HEX 转换、主窗口 UI 与全部交互逻辑
- `config.ini`：自动生成，保存串口参数与界面状态
- `rymculogo.png`：应用图标（由原版 `sources/rymculogo.ico` 转出的 128×128 PNG）
- `build_app.sh` / `make_deb.sh`：打包脚本（生成 Ubuntu 24.04 可用的 `.deb`）
- `dist/rycom_2.6.5_amd64.deb`：已构建的安装包
- `build/`：PyInstaller / dpkg 的临时中间产物



## 从源码运行

依赖PySide6（版本 6.x）：

```bash
python main.py
```

如需在其他环境安装：

```bash
pip install -r requirements.txt
```

## 从源码打包为 deb

使用 conda 中的 PySide6 与 PyInstaller，将程序连同 Qt 运行时一起打包为自包含 deb：

```bash
# 1. 用 PyInstaller 生成单目录可执行（产物在 build/dist/rycom）
bash build_app.sh

# 2. 封装为 deb（产物在 dist/rycom_2.6.5_amd64.deb）
bash make_deb.sh
```

> 注意：`build_app.sh` 中固定使用 `python` 作为打包 Python。
> 包结构：程序装入 `/opt/RYCOM/`，`/usr/bin/rycom` 为启动器，
> 并通过 `.desktop` 与 `hicolor` 图标提供菜单入口。


