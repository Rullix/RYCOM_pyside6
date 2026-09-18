#!/usr/bin/env bash
# 使用 conda 的 PyInstaller 将本目录的 main.py 打包为单目录可执行
# 用法: bash build_app.sh
set -euo pipefail

PY=python
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/main.py"
ICON="$ROOT/rymculogo.png"
DIST="$ROOT/build/dist"
WORK="$ROOT/build/_pyi"

rm -rf "$DIST" "$WORK"
mkdir -p "$ROOT/build"

"$PY" -m PyInstaller \
    --name rycom \
    --onedir \
    --windowed \
    --noconfirm \
    --paths "$ROOT" \
    --hidden-import pyside6_serial \
    --add-data "$ICON:." \
    --exclude-module PySide6.Qt3DAnimation \
    --exclude-module PySide6.Qt3DCore \
    --exclude-module PySide6.Qt3DExtras \
    --exclude-module PySide6.Qt3DInput \
    --exclude-module PySide6.Qt3DLogic \
    --exclude-module PySide6.Qt3DRender \
    --exclude-module PySide6.Qt3DQuick \
    --exclude-module PySide6.QtQml \
    --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtQuickWidgets \
    --exclude-module PySide6.QtQuickControls2 \
    --exclude-module PySide6.QtMultimedia \
    --exclude-module PySide6.QtMultimediaWidgets \
    --exclude-module PySide6.QtWebEngineCore \
    --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.QtWebEngineQuick \
    --exclude-module PySide6.QtWebChannel \
    --exclude-module PySide6.QtWebView \
    --exclude-module PySide6.QtLocation \
    --exclude-module PySide6.QtSensors \
    --exclude-module PySide6.QtBluetooth \
    --exclude-module PySide6.QtPositioning \
    --exclude-module PySide6.QtDesigner \
    --exclude-module PySide6.QtNetworkAuth \
    --exclude-module PySide6.QtRemoteObjects \
    --exclude-module PySide6.QtScxml \
    --exclude-module PySide6.QtStateMachine \
    --exclude-module PySide6.QtCharts \
    --exclude-module PySide6.QtDataVisualization \
    --exclude-module PySide6.QtPdf \
    --exclude-module PySide6.QtPdfWidgets \
    --exclude-module PySide6.QtTextToSpeech \
    --exclude-module PySide6.QtSerialBus \
    --distpath "$DIST" \
    --workpath "$WORK" \
    "$SRC"

# 清理用不到的 Qt 插件以进一步瘦身
APP_DIR="$DIST/rycom"
rm -rf "$APP_DIR/_internal/PySide6/Qt/plugins/sqldrivers"
rm -rf "$APP_DIR/_internal/PySide6/Qt/plugins/qmltooling"
rm -rf "$APP_DIR/_internal/PySide6/Qt/qml"
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt63D"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Qml"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Quick"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Multimedia"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6WebEngine"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Charts"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Location"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Sensors"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Bluetooth"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6Pdf"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6TextToSpeech"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6SerialBus"*
rm -rf "$APP_DIR/_internal/PySide6/Qt/lib/libQt6DataVisualization"*

echo "PyInstaller 产物位于: $DIST/rycom"
