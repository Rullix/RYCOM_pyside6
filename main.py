"""
RYCOM 串口调试工具（PySide6 重构版，单文件自包含）

UI 布局严格还原原版 RYCOM，仅保留串口调试功能：
- 左侧：串口设置 / 接收设置 / 发送设置
- 右侧：接收区 / 多行发送区（默认隐藏，可切换）/ 发送区
- 底部：多行发送开关、周期发送、周期(ms)
- 串口状态指示灯、参数记忆（QSettings）

去除：STM32 / ESP32 下载、Ymodem 文件传输、局域网状态 HTTP 服务。

运行：
    python main.py        # 或 conda 环境的 python
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QSettings, QTimer, QTime, QObject, Signal
from PySide6.QtGui import QTextCursor, QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QComboBox, QPushButton, QCheckBox,
    QRadioButton, QTextEdit, QLabel, QLineEdit, QFileDialog, QMessageBox,
    QGroupBox, QStatusBar,
)
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

def _config_file() -> str:
    """返回 config.ini 的路径。

    源码运行时放在脚本目录（保持原有行为）；打包安装后程序目录（如 /opt/RYCOM）
    对普通用户只读，写入会导致 QSettings 静默失败，故改用用户配置目录。
    """
    base = os.path.dirname(os.path.abspath(__file__))
    if not os.access(base, os.W_OK):
        base = os.path.join(os.path.expanduser("~"), ".config", "RYCOM")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "config.ini")


CONFIG_FILE = _config_file()
WIN_W, WIN_H = 729, 584

BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 74880,
              115200, 230400, 460800, 921600, 1000000, 2000000]
DATA_BITS = [5, 6, 7, 8]
PARITIES = ["None", "Even", "Odd", "Mark", "Space"]
STOP_BITS = ["1", "1.5", "2"]
VERSION_CODE = "2.6.5-PY1"


# ====================================================================== #
# 串口封装
# ====================================================================== #
class SerialPort(QObject):
    ready_read = Signal(bytes)
    opened_changed = Signal(bool)
    error_occurred = Signal(str)
    reconnecting_changed = Signal(bool)

    RECONNECT_INTERVAL_MS = 1000      # 断线后每 1 秒尝试重连一次

    # 端口已不可继续使用的致命错误：设备拔出、资源失效、无权限、设备不存在
    _FATAL_ERRORS = (
        QSerialPort.ResourceError,
        QSerialPort.DeviceNotFoundError,
        QSerialPort.PermissionError,
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = QSerialPort(self)
        self._port.readyRead.connect(self._on_ready_read)
        self._port.errorOccurred.connect(self._on_error)
        self._rx = self._tx = 0
        self._rx_t = self._tx_t = 0.0
        self._user_closed = False     # 用户主动关闭时置位，用于取消自动重连

        # 设备意外断开后每秒尝试重新打开一次（连接句柄保留端口名与参数）
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(self.RECONNECT_INTERVAL_MS)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

    @property
    def is_open(self) -> bool:
        return self._port.isOpen()

    @property
    def is_reconnecting(self) -> bool:
        return self._reconnect_timer.isActive()

    @property
    def port_name(self) -> str:
        return self._port.portName()

    @property
    def rx_bytes(self) -> int:
        return self._rx

    @property
    def tx_bytes(self) -> int:
        return self._tx

    def rx_rate(self) -> float:
        return self._rate(self._rx, self._rx_t)

    def tx_rate(self) -> float:
        return self._rate(self._tx, self._tx_t)

    @staticmethod
    def _rate(total: int, start: float) -> float:
        if not start:
            return 0.0
        dt = time.time() - start
        return (total / 1024.0 / dt) if dt > 0 else 0.0

    def reset_stats(self) -> None:
        self._rx = self._tx = 0
        self._rx_t = self._tx_t = time.time() if self.is_open else 0.0

    def set_port_name(self, name: str) -> None:
        self._port.setPortName(name)

    def set_baud_rate(self, baud: int) -> None:
        self._port.setBaudRate(baud)

    def set_data_bits(self, bits: int) -> None:
        table = {5: QSerialPort.Data5, 6: QSerialPort.Data6,
                 7: QSerialPort.Data7, 8: QSerialPort.Data8}
        if bits in table:
            self._port.setDataBits(table[bits])

    def set_parity(self, parity: str) -> None:
        table = {"None": QSerialPort.NoParity, "Even": QSerialPort.EvenParity,
                 "Odd": QSerialPort.OddParity, "Mark": QSerialPort.MarkParity,
                 "Space": QSerialPort.SpaceParity}
        self._port.setParity(table.get(parity, QSerialPort.NoParity))

    def set_stop_bits(self, stop: str) -> None:
        table = {"1": QSerialPort.OneStop, "1.5": QSerialPort.OneAndHalfStop,
                 "2": QSerialPort.TwoStop}
        self._port.setStopBits(table.get(stop, QSerialPort.OneStop))

    def open(self) -> bool:
        if self._port.open(QSerialPort.ReadWrite):
            self._user_closed = False
            self._stop_reconnect()
            self._rx_t = self._tx_t = time.time()
            self.opened_changed.emit(True)
            return True
        self.error_occurred.emit(self._port.errorString())
        return False

    def close(self) -> None:
        """用户主动关闭：停止自动重连并释放端口。"""
        self._user_closed = True
        self._stop_reconnect()
        if self._port.isOpen():
            self._port.close()
        self.opened_changed.emit(False)

    def send(self, data: bytes) -> int:
        if not self.is_open:
            return 0
        written = self._port.write(data)
        self._port.flush()
        if written > 0:
            self._tx += written
        return written

    def _on_ready_read(self) -> None:
        if not self._port.isOpen():
            return
        data = bytes(self._port.readAll().data())
        if data:
            self._rx += len(data)
            self.ready_read.emit(data)

    def _on_error(self, err: QSerialPort.SerialPortError) -> None:
        if err == QSerialPort.NoError:
            return
        # 自动重连尝试失败时不再刷屏提示错误
        if not self._reconnect_timer.isActive():
            self.error_occurred.emit(self._port.errorString())
        # 设备被拔出 / 资源失效时，Linux 下 QSerialPort 底层 fd 的 notifier 会
        # 持续触发 readyRead，而 readAll() 始终为空，事件循环因此空转占满 CPU。
        # 必须释放该失效句柄以注销 notifier，随后进入“每秒重连一次”的自动重连。
        # 延迟到事件循环空闲执行，避免在 errorOccurred 信号处理中重入关闭。
        if err in self._FATAL_ERRORS and self._port.isOpen():
            QTimer.singleShot(0, self._begin_reconnect)

    def _begin_reconnect(self) -> None:
        """释放失效句柄，并启动每秒一次的自动重连。"""
        if self._user_closed or self._reconnect_timer.isActive():
            return
        if self._port.isOpen():
            self._port.close()
        self._rx_t = self._tx_t = 0.0
        self.reconnecting_changed.emit(True)
        self._reconnect_timer.start()

    def _try_reconnect(self) -> None:
        if self._port.open(QSerialPort.ReadWrite):
            self._stop_reconnect()
            self._rx_t = self._tx_t = time.time()
            self.opened_changed.emit(True)
        # 打开失败则静默等待下一次尝试

    def _stop_reconnect(self) -> None:
        if self._reconnect_timer.isActive():
            self._reconnect_timer.stop()
            self.reconnecting_changed.emit(False)


def scan_ports() -> list[tuple[str, str]]:
    """返回 [(端口名, 描述), ...]。"""
    return [(i.portName(), i.description() or "") for i in QSerialPortInfo.availablePorts()]


def hex_to_bytes(text: str) -> bytes:
    """HEX 文本（空格分隔，可含 0x 前缀）转为字节。"""
    out = bytearray()
    for tok in text.replace("0x", "").replace("0X", "").split():
        try:
            out.append(int(tok, 16))
        except ValueError:
            continue
    return bytes(out)


# ====================================================================== #
# 主窗口
# ====================================================================== #
class MainWindow(QMainWindow):
    _ui_ready = False   # 类级默认：UI 构建完成前不响应 resize 重排

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"RYCOM串口调试助手{VERSION_CODE} rymcu.com嵌入式知识学习交流平台")
        # 仅允许加宽：宽度下限为初始宽度，高度锁定不可调
        self.setMinimumSize(WIN_W, WIN_H)
        self.setMaximumSize(16777215, WIN_H)
        self.resize(WIN_W, WIN_H)

        self.serial = SerialPort(self)

        self._rx_buf = bytearray()
        self._last_rx = 0.0              # 上次接收时刻（用于超时切分）
        self._burst_open = False         # 当前记录是否已加过时间戳
        self._tail_nl = True             # 显示区末尾是否为换行（即处于行首）
        self._stop = self._show_time = False
        self._rx_hex = self._tx_hex = False
        self._encoding = "GBK"          # 原版系统编码
        self._newline = False
        self._muti_last = 0
        self._known_ports: set[str] = set()   # 上次扫描到的端口，用于识别新增设备
        self._ports_inited = False            # 是否已完成首次端口扫描
        self._ui_ready = False                # UI 构建完成前不响应 resize 重排

        self.line_edits: list[QLineEdit] = []
        self.muti_checks: list[QCheckBox] = []

        self._settings = QSettings(CONFIG_FILE, QSettings.IniFormat)

        # 多行发送区输入自动保存（防抖：停止输入约 0.5s 后写盘）
        self._muti_save_timer = QTimer(self)
        self._muti_save_timer.setSingleShot(True)
        self._muti_save_timer.setInterval(500)
        self._muti_save_timer.timeout.connect(self._save_muti_text)

        self._build_ui()
        self._load_settings()
        self._refresh_ports()

        self.serial.ready_read.connect(self._on_data_received)
        self.serial.opened_changed.connect(self._on_opened_changed)
        self.serial.error_occurred.connect(self._on_error)
        self.serial.reconnecting_changed.connect(self._on_reconnecting)

        self._stat_timer = QTimer(self)
        self._stat_timer.setInterval(500)
        self._stat_timer.timeout.connect(self._update_status_bar)
        self._stat_timer.start()

        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._periodic_tick)

        # 未连接时，每 3 秒自动刷新串口列表
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(3000)
        self._scan_timer.timeout.connect(self._refresh_ports)
        self._scan_timer.start()

    # ---------------- UI 构建（绝对坐标，还原原版 mainwindow.ui） ----------------
    def _add(self, w, x, y, ww, hh):
        w.setGeometry(x, y, ww, hh)
        return w

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        mono = QFont("Consolas", 9)
        mono.setStyleHint(QFont.Monospace)

        # 串口设置
        self.gb_com = self._add(QGroupBox("串口设置", central), 10, 0, 171, 201)
        self.cb_port = self._add(QComboBox(self.gb_com), 10, 30, 151, 22)
        self._add(QLabel("波特率", self.gb_com), 11, 61, 39, 18)
        self.cb_baud = QComboBox(self.gb_com)
        self.cb_baud.setEditable(True)
        self.cb_baud.addItems([str(b) for b in BAUD_RATES] + ["自定义"])
        self._add(self.cb_baud, 70, 60, 91, 22)
        self._add(QLabel("数据位", self.gb_com), 11, 88, 39, 18)
        self.cb_data = QComboBox(self.gb_com)
        self.cb_data.addItems([str(d) for d in DATA_BITS])
        self._add(self.cb_data, 70, 87, 91, 22)
        self._add(QLabel("停止位", self.gb_com), 11, 115, 39, 18)
        self.cb_stop = QComboBox(self.gb_com)
        self.cb_stop.addItems(STOP_BITS)
        self._add(self.cb_stop, 70, 113, 91, 22)
        self._add(QLabel("校验位", self.gb_com), 11, 141, 39, 18)
        self.cb_parity = QComboBox(self.gb_com)
        self.cb_parity.addItems(PARITIES)
        self._add(self.cb_parity, 70, 139, 91, 22)
        self.led = QRadioButton(self.gb_com)
        self.led.setGeometry(20, 160, 31, 41)
        self.led.setEnabled(False)
        self.led.setStyleSheet(
            "QRadioButton::indicator{width:18px;height:18px;border-radius:9px;}"
            "QRadioButton::indicator:unchecked{background:#444;border:1px solid #000;}"
            "QRadioButton::indicator:checked{background:red;border:1px solid #800;}")
        self.btn_open = self._add(QPushButton("打开串口", self.gb_com), 70, 170, 91, 22)

        # 接收设置
        self.gb_revset = self._add(QGroupBox("接收设置", central), 10, 200, 171, 161)
        self.btn_save_rev = self._add(QPushButton("保存文件", self.gb_revset), 70, 30, 91, 22)
        self.btn_stop_rev = self._add(QPushButton("停止显示", self.gb_revset), 70, 55, 91, 22)
        self.btn_clear_rev = self._add(QPushButton("清空接收区", self.gb_revset), 70, 79, 91, 22)
        self.cb_rev_time = self._add(QCheckBox("接收时间", self.gb_revset), 76, 114, 77, 22)
        self.cb_rev_hex = self._add(QCheckBox("十六进制", self.gb_revset), 76, 137, 77, 22)

        # 发送设置
        self.gb_sendset = self._add(QGroupBox("发送设置", central), 10, 382, 171, 151)
        self.btn_rd_file = self._add(QPushButton("读取文件", self.gb_sendset), 70, 25, 91, 22)
        self.btn_clear_send = self._add(QPushButton("清空发送区", self.gb_sendset), 70, 52, 91, 22)
        self.cb_send_hex = self._add(QCheckBox("十六进制", self.gb_sendset), 76, 80, 101, 22)
        self.cb_add_newline = self._add(QCheckBox("发送新行", self.gb_sendset), 76, 103, 101, 22)

        # 接收区
        self.gb_rev = self._add(QGroupBox("接收区", central), 180, 0, 541, 361)
        self.te_recv = QTextEdit(self.gb_rev)
        self.te_recv.setReadOnly(True)
        self.te_recv.setLineWrapMode(QTextEdit.NoWrap)
        self.te_recv.setFont(mono)
        self._add(self.te_recv, 10, 30, 521, 321)

        # 多行发送区（默认隐藏）
        self.gb_mutisend = self._add(QGroupBox("多行发送区", central), 530, 0, 191, 361)
        self.gb_mutisend.hide()
        self._add(QLabel("选中", self.gb_mutisend), 10, 20, 41, 16)
        self._add(QLabel("输入字符", self.gb_mutisend), 60, 20, 61, 16)
        self._add(QLabel("发送", self.gb_mutisend), 160, 20, 31, 16)
        for i, y in enumerate([44, 72, 100, 127, 156, 184, 212, 239, 269, 299]):
            ch = self._add(QCheckBox(self.gb_mutisend), 9, y, 16, 16)
            self.muti_checks.append(ch)
            le = QLineEdit(self.gb_mutisend)
            le.setText(str(i + 1))
            le.setFont(mono)
            self._add(le, 30, y, 121, 20)
            le.textChanged.connect(self._on_muti_text_changed)   # 输入即自动保存
            self.line_edits.append(le)
            btn = self._add(QPushButton(str(i + 1), self.gb_mutisend), 158, y - 2, 31, 23)
            btn.clicked.connect(lambda _=False, n=i: self._send_line(n))
        self.btn_muti_reset = self._add(QPushButton("复位", self.gb_mutisend), 10, 330, 31, 23)
        self.btn_muti_reset.clicked.connect(self._reset_mutisend)
        self.cb_periodic_muti = self._add(QCheckBox("多行循环发送", self.gb_mutisend), 50, 330, 131, 23)

        # 发送区
        self.gb_send = self._add(QGroupBox("发送区", central), 180, 382, 541, 151)
        self.te_send = QTextEdit(self.gb_send)
        self.te_send.setLineWrapMode(QTextEdit.NoWrap)
        self.te_send.setFont(mono)
        self._add(self.te_send, 10, 30, 521, 111)
        self.btn_send = self._add(QPushButton("发送", self.gb_send), 500, 120, 31, 21)

        # 底部开关（原版浮动在发送区上方）
        self.rb_multiline = QRadioButton("多行发送", central)
        self.rb_multiline.setAutoExclusive(False)
        self._add(self.rb_multiline, 477, 372, 81, 16)
        self.cb_periodic_send = self._add(QCheckBox("周期发送", central), 558, 372, 81, 16)
        self.le_time = self._add(QLineEdit("1000", central), 639, 372, 52, 16)
        self.lbl_ms = self._add(QLabel("ms", central), 695, 372, 16, 16)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self._lbl_status = QLabel("未打开")
        self._lbl_rx = QLabel("RX: 0 B")
        self._lbl_tx = QLabel("TX: 0 B")
        self._lbl_rx_rate = QLabel("RX: 0.0 KB/s")
        self._lbl_tx_rate = QLabel("TX: 0.0 KB/s")
        for w in (self._lbl_status, self._lbl_rx, self._lbl_tx,
                  self._lbl_rx_rate, self._lbl_tx_rate):
            self.statusBar().addPermanentWidget(w)

        # 菜单栏
        about = QAction("关于", self)
        about.triggered.connect(self._about)
        clear = QAction("清空统计", self)
        clear.triggered.connect(self.serial.reset_stats)
        menu = self.menuBar().addMenu("文件")
        menu.addAction(clear)
        menu.addSeparator()
        menu.addAction(about)

        # 信号连接
        self.btn_open.clicked.connect(self._toggle_port)
        self.btn_save_rev.clicked.connect(self._save_received)
        self.btn_stop_rev.clicked.connect(self._toggle_stop_display)
        self.btn_clear_rev.clicked.connect(self.te_recv.clear)
        self.btn_rd_file.clicked.connect(self._load_to_send)
        self.btn_clear_send.clicked.connect(self.te_send.clear)
        self.btn_send.clicked.connect(self._send_once)
        self.cb_rev_hex.toggled.connect(lambda v: setattr(self, "_rx_hex", v))
        self.cb_send_hex.toggled.connect(lambda v: setattr(self, "_tx_hex", v))
        self.cb_rev_time.toggled.connect(lambda v: setattr(self, "_show_time", v))
        self.cb_add_newline.toggled.connect(lambda v: setattr(self, "_newline", v))
        self.rb_multiline.toggled.connect(self._apply_multiline_layout)
        self.cb_periodic_send.toggled.connect(self._on_periodic_send)
        self.cb_periodic_muti.toggled.connect(self._on_periodic_muti)

        # 初值
        self.cb_baud.setCurrentText("115200")
        self.cb_data.setCurrentText("8")
        self.cb_parity.setCurrentText("None")
        self.cb_stop.setCurrentText("1")
        self._apply_multiline_layout(False)
        self._ui_ready = True

    # ---------------- 串口操作 ----------------
    def _refresh_ports(self) -> None:
        """刷新端口列表。空闲状态下若有新设备接入，自动选中该新增设备。"""
        ports = scan_ports()
        names = {name for name, _ in ports}
        added = names - self._known_ports      # 本次新增的端口
        current = self.cb_port.currentData()

        self.cb_port.clear()
        for name, desc in ports:
            self.cb_port.addItem(f"{name} ({desc})" if desc else name, name)
        self._known_ports = names

        if not self._ports_inited:
            # 首次扫描：恢复上次使用的端口，不做“新增”判定
            self._ports_inited = True
            saved = self._settings.value("port")
            idx = self.cb_port.findData(saved) if saved else -1
            if idx >= 0:
                self.cb_port.setCurrentIndex(idx)
            return

        if added and not self.serial.is_open:
            # 有新设备接入（多个时取列表中最后一个）→ 自动选中
            target = next((n for n, _ in reversed(ports) if n in added), None)
            idx = self.cb_port.findData(target)
            if idx >= 0:
                self.cb_port.setCurrentIndex(idx)
                return

        if current:
            idx = self.cb_port.findData(current)
            if idx >= 0:
                self.cb_port.setCurrentIndex(idx)

    def _toggle_port(self) -> None:
        if self.serial.is_reconnecting:
            # 重连中点击按钮 = 停止重连，回到未打开状态
            self.serial.close()
            return
        if self.serial.is_open:
            self._periodic_timer.stop()
            self.cb_periodic_send.setChecked(False)
            self.cb_periodic_muti.setChecked(False)
            self.serial.close()
            return
        name = self.cb_port.currentData()
        if not name:
            QMessageBox.warning(self, "提示", "请先选择串口")
            return
        self.serial.set_port_name(name)
        try:
            self.serial.set_baud_rate(int(self.cb_baud.currentText()))
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率无效")
            return
        self.serial.set_data_bits(int(self.cb_data.currentText()))
        self.serial.set_parity(self.cb_parity.currentText())
        self.serial.set_stop_bits(self.cb_stop.currentText())
        if not self.serial.open():
            QMessageBox.critical(self, "错误", "无法打开串口，请检查权限或占用。")

    def _on_opened_changed(self, opened: bool) -> None:
        self.btn_open.setText("关闭串口" if opened else "打开串口")
        self.led.setChecked(opened)
        self._lbl_status.setText(f"{self.serial.port_name} 已打开" if opened else "未打开")
        for w in (self.cb_port, self.cb_baud, self.cb_data, self.cb_parity, self.cb_stop):
            w.setEnabled(not opened)
        if opened:
            self.serial.reset_stats()
            self._scan_timer.stop()
        else:
            # 端口关闭（含设备被拔出导致的意外关闭）：停止周期发送，复位相关控件
            self._periodic_timer.stop()
            self.cb_periodic_send.setChecked(False)
            self.cb_periodic_muti.setChecked(False)
            self.le_time.setEnabled(True)
            self._scan_timer.start()

    def _on_reconnecting(self, active: bool) -> None:
        """设备意外断开后进入自动重连状态（每秒重试），UI 保持连接语义。"""
        if not active:
            return
        self.led.setChecked(False)
        self.btn_open.setText("停止重连")
        self._lbl_status.setText(f"{self.serial.port_name} 已断开，正在重连...")
        for w in (self.cb_port, self.cb_baud, self.cb_data, self.cb_parity, self.cb_stop):
            w.setEnabled(False)
        self._periodic_timer.stop()
        self.cb_periodic_send.setChecked(False)
        self.cb_periodic_muti.setChecked(False)
        self.le_time.setEnabled(True)
        self._scan_timer.stop()

    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"串口错误: {msg}", 5000)

    # ---------------- 接收 ----------------
    def _on_data_received(self, data: bytes) -> None:
        if self._stop:
            self._rx_buf.extend(data)
        else:
            self._display(data)

    def _display(self, data: bytes) -> None:
        """超时切分：相邻数据块间隔小于阈值视为同一记录，仅起始加一次时间戳；
        超过阈值视为新记录，重新加时间戳。避免时间戳穿插在字符中间。"""
        BURST_MS = 100  # 超时阈值(ms)：间隔超过则视为新记录
        now = time.time()
        new_burst = (now - self._last_rx) * 1000 > BURST_MS
        self._last_rx = now
        if new_burst:
            self._burst_open = False  # 新记录尚未加时间戳

        if self._rx_hex:
            body = " ".join(f"{b:02X}" for b in data)
        else:
            try:
                body = data.decode(self._encoding, errors="replace")
            except LookupError:
                body = data.decode("ascii", errors="replace")
            body = body.rstrip("\r")

        prefix = ""
        if self._show_time and not self._burst_open:
            if not self._tail_nl:       # 当前不在行首则先换行
                prefix = "\n"
            prefix += self._ts()
            self._burst_open = True

        text = prefix + body
        self.te_recv.insertPlainText(text)
        self.te_recv.moveCursor(QTextCursor.End)
        self._tail_nl = text.endswith("\n")

    def _toggle_stop_display(self) -> None:
        self._stop = not self._stop
        if not self._stop and self._rx_buf:
            buf = bytes(self._rx_buf)
            self._rx_buf.clear()
            self._display(buf)

    def _ts(self) -> str:
        return f"[{QTime.currentTime().toString('HH:mm:ss.zzz')}] "

    # ---------------- 发送 ----------------
    def _build_send_bytes(self, text: str) -> bytes:
        text = text.rstrip("\n").rstrip("\r")
        if self._tx_hex:
            return hex_to_bytes(text)
        data = text.encode(self._encoding, errors="replace")
        if self._newline:
            data += b"\r\n"
        return data

    def _send_once(self) -> None:
        text = self.te_send.toPlainText()
        if text.strip():
            self.serial.send(self._build_send_bytes(text))

    def _send_line(self, n: int) -> None:
        if 0 <= n < len(self.line_edits):
            text = self.line_edits[n].text()
            if text.strip():
                self.serial.send(self._build_send_bytes(text))

    def _reset_mutisend(self) -> None:
        for le in self.line_edits:
            le.clear()
        for ch in self.muti_checks:
            ch.setChecked(False)
        self._muti_last = 0

    # ---------------- 多行发送区自动保存 ----------------
    def _on_muti_text_changed(self, _text: str) -> None:
        """输入变化时防抖触发自动保存。"""
        self._muti_save_timer.start()

    def _save_muti_text(self) -> None:
        """把多行发送区各行文本写入配置并落盘。"""
        s = self._settings
        for i, le in enumerate(self.line_edits):
            s.setValue(f"muti_text_{i}", le.text())
        s.sync()

    # ---------------- 发送区域切换 / 窗口尺寸自适应 ----------------
    def _apply_multiline_layout(self, checked: bool) -> None:
        self.gb_mutisend.setVisible(checked)
        self._relayout()

    def _relayout(self) -> None:
        """宽度变化时重排：左侧三个设置栏保持原尺寸，仅接收区/发送区随宽度伸缩。
        额外宽度 d 以初始宽度 WIN_W 为基准。"""
        d = max(0, self.width() - WIN_W)
        if self.rb_multiline.isChecked():
            # 多行模式：接收区变窄，右侧仍是原尺寸的多行发送区（整体右移）
            self.gb_rev.setGeometry(180, 0, 341 + d, 361)
            self.te_recv.setGeometry(10, 30, 321 + d, 321)
            self.gb_mutisend.setGeometry(530 + d, 0, 191, 361)
        else:
            self.gb_rev.setGeometry(180, 0, 541 + d, 361)
            self.te_recv.setGeometry(10, 30, 521 + d, 321)
            self.gb_mutisend.setGeometry(530, 0, 191, 361)

        # 发送区
        self.gb_send.setGeometry(180, 382, 541 + d, 151)
        self.te_send.setGeometry(10, 30, 521 + d, 111)
        self.btn_send.setGeometry(500 + d, 120, 31, 21)

        # 底部开关（跟随右边缘移动；时间框加宽以显示 5 位数）
        self.rb_multiline.setGeometry(477 + d, 372, 81, 16)
        self.cb_periodic_send.setGeometry(558 + d, 372, 81, 16)
        self.le_time.setGeometry(639 + d, 372, 52, 16)
        self.lbl_ms.setGeometry(695 + d, 372, 16, 16)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._ui_ready:
            self._relayout()

    # ---------------- 周期 / 多行循环发送 ----------------
    def _start_periodic(self) -> None:
        try:
            interval = max(10, int(self.le_time.text()))
        except ValueError:
            interval = 1000
        self._muti_last = 0
        self._periodic_timer.start(interval)
        self.le_time.setEnabled(False)

    def _on_periodic_send(self, checked: bool) -> None:
        if checked:
            if not self.serial.is_open:
                QMessageBox.warning(self, "提示", "请先打开串口再开启周期发送")
                self.cb_periodic_send.setChecked(False)
                return
            self.cb_periodic_muti.setChecked(False)
            self._start_periodic()
        else:
            self._periodic_timer.stop()
            self.le_time.setEnabled(True)

    def _on_periodic_muti(self, checked: bool) -> None:
        if checked:
            if not self.serial.is_open:
                QMessageBox.warning(self, "提示", "请先打开串口再开启循环发送")
                self.cb_periodic_muti.setChecked(False)
                return
            self.cb_periodic_send.setChecked(False)
            self._start_periodic()
        else:
            self._periodic_timer.stop()
            self.le_time.setEnabled(True)

    def _periodic_tick(self) -> None:
        if self.cb_periodic_muti.isChecked():
            n = len(self.line_edits)
            for i in range(n):
                idx = (self._muti_last + i) % n
                if self.muti_checks[idx].isChecked():
                    self._muti_last = idx + 1
                    self._send_line(idx)
                    return
        else:
            self._send_once()

    # ---------------- 文件 ----------------
    def _save_received(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存接收内容", "", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.te_recv.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _load_to_send(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "读入发送文件", "", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.te_send.setPlainText(f.read())
        except OSError as e:
            QMessageBox.critical(self, "错误", f"读取失败: {e}")

    # ---------------- 状态栏 ----------------
    def _update_status_bar(self) -> None:
        self._lbl_rx.setText(f"RX: {self.serial.rx_bytes} B")
        self._lbl_tx.setText(f"TX: {self.serial.tx_bytes} B")
        self._lbl_rx_rate.setText(f"RX: {self.serial.rx_rate():.1f} KB/s")
        self._lbl_tx_rate.setText(f"TX: {self.serial.tx_rate():.1f} KB/s")

    def _about(self) -> None:
        QMessageBox.information(
            self, "关于",
            "RYCOM 串口调试工具 PySide6 重构版\n"
            "基于原程序版本：2.6.5 ，仅保留串口调试功能\n"
            "本项目：https://github.com/Rullix/RYCOM_pyside6\n"
            "原项目：https://github.com/rymcu/RYCOM")

    # ---------------- 参数记忆 ----------------
    def _load_settings(self) -> None:
        s = self._settings
        if s.contains("port"):
            idx = self.cb_port.findData(s.value("port"))
            if idx >= 0:
                self.cb_port.setCurrentIndex(idx)
        self.cb_baud.setCurrentText(str(s.value("baud", 115200)))
        self.cb_data.setCurrentText(s.value("data", "8"))
        self.cb_parity.setCurrentText(s.value("parity", "None"))
        self.cb_stop.setCurrentText(s.value("stop", "1"))
        self.cb_rev_hex.setChecked(s.value("rx_hex", False, type=bool))
        self.cb_send_hex.setChecked(s.value("tx_hex", False, type=bool))
        self.cb_rev_time.setChecked(s.value("show_time", False, type=bool))
        self.cb_add_newline.setChecked(s.value("newline", False, type=bool))
        self.le_time.setText(str(s.value("interval", 1000)))
        self.rb_multiline.setChecked(s.value("multiline", False, type=bool))
        self._apply_multiline_layout(self.rb_multiline.isChecked())
        # 多行发送区各行文本
        for i, le in enumerate(self.line_edits):
            key = f"muti_text_{i}"
            if s.contains(key):
                le.setText(str(s.value(key)))

    def _save_settings(self) -> None:
        s = self._settings
        s.setValue("port", self.cb_port.currentData())
        s.setValue("baud", self.cb_baud.currentText())
        s.setValue("data", self.cb_data.currentText())
        s.setValue("parity", self.cb_parity.currentText())
        s.setValue("stop", self.cb_stop.currentText())
        s.setValue("rx_hex", self.cb_rev_hex.isChecked())
        s.setValue("tx_hex", self.cb_send_hex.isChecked())
        s.setValue("show_time", self.cb_rev_time.isChecked())
        s.setValue("newline", self.cb_add_newline.isChecked())
        s.setValue("interval", self.le_time.text())
        s.setValue("multiline", self.rb_multiline.isChecked())
        self._save_muti_text()   # 多行发送区文本一并落盘

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_settings()
        self._periodic_timer.stop()
        self.serial.close()   # 停止自动重连并释放端口
        event.accept()


def main() -> None:
    app = QApplication([])
    app.setApplicationName("RYCOM")
    win = MainWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
