# PrefLight の表示ウインドウを自動で録画する／録画の Ctrl+Shift+R を送る（Windows・標準ライブラリ＋ffmpeg）
# 使い方:
#   py -3.12 tools/preflight_capture.py --find                       # PrefLight の窓一覧（ハンドル・位置・大きさ）
#   py -3.12 tools/preflight_capture.py --record out.mp4 --seconds 70   # 表示ウインドウの領域を ffmpeg(gdigrab) で録画
#   py -3.12 tools/preflight_capture.py --hotkey                     # 表示ウインドウを前面にして Ctrl+Shift+R（PrefLight 側の録画 開始/停止）
# 表示ウインドウ = タイトルに PrefLight を含み、メニューを持たない方（ヘルプ「表示ウインドウ」）。見つからなければ一番大きい窓。
import argparse
import ctypes
import ctypes.wintypes as w
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def windows(keyword="PrefLight"):
    out = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1); user32.GetWindowTextW(hwnd, buf, n + 1)
        if keyword in buf.value:
            r = w.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
            c = w.RECT(); user32.GetClientRect(hwnd, ctypes.byref(c))
            pt = w.POINT(0, 0); user32.ClientToScreen(hwnd, ctypes.byref(pt))
            has_menu = bool(user32.GetMenu(hwnd))
            out.append({"hwnd": hwnd, "title": buf.value, "x": pt.x, "y": pt.y, "w": c.right, "h": c.bottom, "menu": has_menu})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def display_window():
    ws = [x for x in windows() if x["title"].rstrip().endswith("-PrefLight")]  # アプリ本体の窓だけ（エクスプローラー等を除く）
    if not ws:
        raise SystemExit("PrefLight の窓が見つからない")
    nomenu = [x for x in ws if not x["menu"]]
    return max(nomenu or ws, key=lambda x: x["w"] * x["h"])


PS_CAPTURE = r"""
param([int]$x,[int]$y,[int]$w,[int]$h,[double]$seconds,[int]$fps,[string]$dir)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$i = 0; $interval = 1000.0 / $fps
while ($sw.Elapsed.TotalSeconds -lt $seconds) {
  $g.CopyFromScreen($x, $y, 0, 0, $bmp.Size)
  $bmp.Save((Join-Path $dir ("{0:D5}.bmp" -f $i)), [System.Drawing.Imaging.ImageFormat]::Bmp)
  $i++
  $wait = $i * $interval - $sw.Elapsed.TotalMilliseconds
  if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]$wait) }
}
Write-Output ("frames={0} seconds={1:F2}" -f $i, $sw.Elapsed.TotalSeconds)
"""


def record_screen(path, seconds, fps=20):
    """RDP 越しでも撮れる方式: .NET の CopyFromScreen で BMP 連番を撮り、ffmpeg で mp4 にする（gdigrab/ddagrab は RDP で黒や拒否になる）"""
    import os, shutil, tempfile
    d = display_window()
    x, y, ww, hh = d["x"], d["y"], d["w"] - d["w"] % 2, d["h"] - d["h"] % 2
    tmp = tempfile.mkdtemp(prefix="plcap-")
    ps = os.path.join(tmp, "cap.ps1")
    open(ps, "w", encoding="utf-8").write(PS_CAPTURE)
    print(f"録画(画面複写) {d['title']} 領域 {x},{y} {ww}x{hh} {fps}fps {seconds}s → {path}")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, "-x", str(x), "-y", str(y), "-w", str(ww), "-h", str(hh), "-seconds", str(seconds), "-fps", str(fps), "-dir", tmp], capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip()[:300])
    rc = subprocess.call(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(tmp, "%05d.bmp"), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", path])
    shutil.rmtree(tmp, ignore_errors=True)
    return rc


def record(path, seconds, fps=30):
    d = display_window()
    x, y, ww, hh = d["x"], d["y"], d["w"] - d["w"] % 2, d["h"] - d["h"] % 2
    print(f"録画 {d['title']} hwnd={d['hwnd']} 領域 {x},{y} {ww}x{hh} → {path}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "gdigrab", "-framerate", str(fps), "-offset_x", str(x), "-offset_y", str(y),
           "-video_size", f"{ww}x{hh}", "-i", "desktop", "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", path]
    return subprocess.call(cmd)


def hotkey():
    d = display_window()
    hwnd = d["hwnd"]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    fg = user32.GetForegroundWindow()
    # SendInput で Ctrl+Shift+R
    INPUT_KEYBOARD = 1; KEYEVENTF_KEYUP = 2
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
    class INPUT(ctypes.Structure):
        class U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("u",); _fields_ = [("type", w.DWORD), ("u", U)]
    def key(vk, up=False):
        i = INPUT(type=INPUT_KEYBOARD); i.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None); return i
    seq = [key(0x11), key(0x10), key(0x52), key(0x52, True), key(0x10, True), key(0x11, True)]  # Ctrl, Shift, R
    arr = (INPUT * len(seq))(*seq)
    n = user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
    print(f"前面={'OK' if fg == hwnd else 'NG(' + str(fg) + ')'} 送信={n}/6 → {d['title']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", action="store_true"); ap.add_argument("--record"); ap.add_argument("--seconds", type=float, default=70); ap.add_argument("--hotkey", action="store_true")
    ap.add_argument("--screen", help="画面複写で録画（RDP 越し向け・20fps）")
    a = ap.parse_args()
    if a.find:
        for x in windows():
            print(x)
    if a.screen:
        sys.exit(record_screen(a.screen, a.seconds))
    if a.record:
        sys.exit(record(a.record, a.seconds))
    if a.hotkey:
        hotkey()
