#!/usr/bin/env python3
"""
Pixel Tool - 桌面宠物自定义像素工具
功能：图片/GIF -> .pxl转换，.pxl文件发送到ESP32
"""
import sys
import os
import argparse
import struct
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pxl_encoder import image_to_pxl, gif_to_pxl, png_to_pxl_frames
from pxl_sender import send_pxl_to_esp32, send_pixel_command


def cmd_convert(args: Any) -> int:
    """转换命令：图片/GIF -> .pxl（带进度条）"""
    src = Path(args.input)
    if not src.exists():
        print(f"[ERR] 文件不存在: {src}")
        return 1
    out = args.output
    size = (args.width, args.height)

    # 简易进度回调
    def progress_cb(current: int, total: int):
        if total > 0:
            pct = current * 100 // total
            bar_len = 30
            filled = bar_len * current // total
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r[{bar}] {pct}% ({current}/{total}帧)", end='', flush=True)

    try:
        if src.suffix.lower() == '.gif':
            gif_to_pxl(str(src), out, size, args.max_frames, args.loop, progress_cb=progress_cb)
        elif src.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
            if args.sprite:
                png_to_pxl_frames(str(src), out, size, args.interval, progress_cb=progress_cb)
            else:
                image_to_pxl(str(src), out, size, args.interval, args.loop)
        else:
            print(f"[ERR] 不支持的格式: {src.suffix}")
            return 1
        print()  # 换行结束进度条
    except Exception as e:
        print(f"\n[ERR] 转换失败: {e}")
        return 1
    return 0


def cmd_send(args: Any) -> int:
    """发送命令：.pxl -> ESP32"""
    pxl = Path(args.file)
    if not pxl.exists():
        print(f"[ERR] 文件不存在: {pxl}")
        return 1
    ok = send_pxl_to_esp32(
        str(pxl), args.host, args.port,
        timeout=args.timeout,
        switch_mode=not args.no_switch
    )
    return 0 if ok else 1


def cmd_cmd(args: Any) -> int:
    """控制命令：发送控制指令到ESP32"""
    ok = send_pixel_command(args.host, args.port, args.command, args.mode)
    return 0 if ok else 1


def cmd_info(args: Any) -> int:
    """信息命令：查看.pxl文件信息"""
    pxl = Path(args.file)
    if not pxl.exists():
        print(f"[ERR] 文件不存在: {pxl}")
        return 1

    with open(pxl, 'rb') as f:
        data = f.read()

    if len(data) < 16:
        print("[ERR] 文件太小，不是有效的.pxl文件")
        return 1
    if data[0:3] != b'PXL':
        print("[ERR] 不是PXL格式文件")
        return 1

    version = data[3]
    width = struct.unpack_from('<H', data, 4)[0]
    height = struct.unpack_from('<H', data, 6)[0]
    frame_count = struct.unpack_from('<H', data, 8)[0]
    frame_interval = struct.unpack_from('<H', data, 10)[0]
    flags = struct.unpack_from('<H', data, 12)[0]

    pixel_size = width * height * frame_count * 2
    file_size = len(data)
    expected = 16 + pixel_size

    print(f"[INFO] PXL 文件信息: {pxl.name}")
    print(f"   格式版本: {version}")
    print(f"   尺寸:     {width}x{height}")
    print(f"   帧数:     {frame_count} ({'动画' if frame_count > 1 else '静态'})")
    print(f"   帧间隔:   {frame_interval}ms")
    print(f"   循环播放: {'是' if flags & 1 else '否'}")
    print(f"   像素数据: {pixel_size} bytes")
    print(f"   文件大小: {file_size} bytes")
    if file_size != expected:
        print(f"   [WARN] 文件大小不匹配! 期望 {expected} bytes")
    else:
        print(f"   [OK] 文件格式正确")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Pixel Tool - 桌面宠物自定义像素工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s convert image.png                     # 图片->.pxl
  %(prog)s convert animation.gif -o my.pxl       # GIF->.pxl
  %(prog)s convert spritesheet.png --sprite       # 雪碧图->.pxl
  %(prog)s send my.pxl 192.168.1.100             # 发送到ESP32
  %(prog)s info my.pxl                           # 查看.pxl信息
  %(prog)s cmd switch_mode 192.168.1.100 -m pixel  # 切换模式
        """
    )
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # convert
    p_convert = subparsers.add_parser('convert', help='转换图片/GIF为.pxl')
    p_convert.add_argument('input', help='输入图片/GIF路径')
    p_convert.add_argument('-o', '--output', help='输出.pxl路径')
    p_convert.add_argument('-W', '--width', type=int, default=32, help='目标宽度(默认32)')
    p_convert.add_argument('-H', '--height', type=int, default=32, help='目标高度(默认32)')
    p_convert.add_argument('-i', '--interval', type=int, default=200, help='帧间隔ms(默认200)')
    p_convert.add_argument('--max-frames', type=int, default=16, help='GIF最大帧数(默认16)')
    p_convert.add_argument('--no-loop', dest='loop', action='store_false', help='不循环播放')
    p_convert.add_argument('--sprite', action='store_true', help='雪碧图模式(水平排列的帧序列)')
    p_convert.set_defaults(func=cmd_convert)

    # send
    p_send = subparsers.add_parser('send', help='发送.pxl到ESP32')
    p_send.add_argument('file', help='.pxl文件路径')
    p_send.add_argument('host', help='ESP32 IP地址')
    p_send.add_argument('-p', '--port', type=int, default=19876, help='端口(默认19876)')
    p_send.add_argument('-t', '--timeout', type=float, default=10.0, help='超时秒数')
    p_send.add_argument('--no-switch', action='store_true', help='不自动切换到像素模式')
    p_send.set_defaults(func=cmd_send)

    # info
    p_info = subparsers.add_parser('info', help='查看.pxl文件信息')
    p_info.add_argument('file', help='.pxl文件路径')
    p_info.set_defaults(func=cmd_info)

    # cmd
    p_cmd = subparsers.add_parser('cmd', help='发送控制命令')
    p_cmd.add_argument('command', choices=['play', 'pause', 'stop', 'switch_mode'], help='命令')
    p_cmd.add_argument('host', help='ESP32 IP地址')
    p_cmd.add_argument('-p', '--port', type=int, default=19876, help='端口')
    p_cmd.add_argument('-m', '--mode', choices=['normal', 'pixel'], help='目标模式')
    p_cmd.set_defaults(func=cmd_cmd)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
