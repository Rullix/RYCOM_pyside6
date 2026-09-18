#!/usr/bin/env bash
# 将 PyInstaller 产物封装为可在 Ubuntu 24.04 (amd64) 安装的 .deb
# 用法: 先 bash build_app.sh, 再 bash make_deb.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP=rycom
APPNAME=RYCOM
ARCH=amd64

# 版本号取自 main.py 的 VERSION_CODE（去掉前缀 V/v）
MAIN_PY="$ROOT/main.py"
VERSION_CODE="$(sed -nE 's/^VERSION_CODE[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$MAIN_PY" | head -n1)"
if [[ -z "$VERSION_CODE" ]]; then
    echo "错误：无法从 $MAIN_PY 读取 VERSION_CODE" >&2
    exit 1
fi
VERSION="${VERSION_CODE#[Vv]}"
echo "版本号: $VERSION_CODE -> $VERSION"
PKGDIR="$ROOT/build/pkg"
SRC_DIST="$ROOT/build/dist/rycom"
ICON_SRC="$ROOT/rymculogo.png"

# 清理重建
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR/opt/RYCOM"
mkdir -p "$PKGDIR/usr/bin"
mkdir -p "$PKGDIR/usr/share/applications"
mkdir -p "$PKGDIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$PKGDIR/DEBIAN"

# 1) 复制可执行目录到 /opt/RYCOM
cp -r "$SRC_DIST"/. "$PKGDIR/opt/RYCOM/"

# 2) 创建 /usr/bin 启动器（wrapper）
cat > "$PKGDIR/usr/bin/$APP" <<'EOF'
#!/usr/bin/env bash
exec /opt/RYCOM/rycom "$@"
EOF
chmod 755 "$PKGDIR/usr/bin/$APP"

# 3) 桌面入口文件
cat > "$PKGDIR/usr/share/applications/$APP.desktop" <<EOF
[Desktop Entry]
Version=$VERSION
Type=Application
Name=$APPNAME
GenericName=Serial Port Tool
Comment=RYCOM serial port assistant
Exec=$APP
Icon=$APP
Terminal=false
Categories=Development;Utility;
StartupNotify=true
EOF

# 4) 图标
cp "$ICON_SRC" "$PKGDIR/usr/share/icons/hicolor/128x128/apps/$APP.png"

# 5) DEBIAN/control
INSTALLED_SIZE=$(du -sk "$PKGDIR/opt" | cut -f1)
cat > "$PKGDIR/DEBIAN/control" <<EOF
Package: $APP
Version: $VERSION
Section: electronics
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: RYMCU <support@rymcu.com>
Description: RYCOM serial port assistant
 RYCOM is a cross-platform serial port debugging tool with
 text/HEX display, periodic sending, multi-line sending,
 file transfer and other features.
EOF

# 6) DEBIAN/postinst：刷新图标缓存与桌面数据库
cat > "$PKGDIR/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env bash
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "$PKGDIR/DEBIAN/postinst"

# 7) 生成 deb
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${APP}_${VERSION}_${ARCH}.deb"
rm -f "$OUT"
fakeroot dpkg-deb --build "$PKGDIR" "$OUT"
echo "已生成: $OUT"
ls -lh "$OUT"
