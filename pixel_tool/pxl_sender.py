"""
PXL 像素文件发送器
通过TCP将.pxl文件发送到ESP32桌面宠物
"""
import socket
import json
import time
import base64
import struct
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_PIXEL_BYTES = 1024

# 网络参数
DEFAULT_ESP32_PORT = 19876
SEND_TIMEOUT = 10.0       # 发送超时(秒)
CMD_TIMEOUT = 5.0         # 命令超时(秒)
CHUNK_SEND_DELAY = 0.05   # 包间延迟(秒)
MODE_SWITCH_DELAY = 0.1   # 模式切换延迟(秒)
PXL_HEADER_BYTES = 16     # PXL文件头大小


def pxl_to_base64_chunks(pxl_path: str, chunk_size: int = CHUNK_PIXEL_BYTES) -> list:
    """读取.pxl文件，解析头部，返回分包数据列表"""
    pxl_path = Path(pxl_path)
    if not pxl_path.exists():
        raise FileNotFoundError(f"文件不存在: {pxl_path}")

    with open(pxl_path, 'rb') as f:
        data = f.read()

    if len(data) < PXL_HEADER_BYTES:
        raise ValueError("文件太小，不是有效的.pxl文件")
    if data[0:3] != b'PXL':
        raise ValueError("不是PXL格式文件")

    width = struct.unpack_from('<H', data, 4)[0]
    height = struct.unpack_from('<H', data, 6)[0]
    frame_count = struct.unpack_from('<H', data, 8)[0]
    frame_interval = struct.unpack_from('<H', data, 10)[0]
    flags = struct.unpack_from('<H', data, 12)[0]

    pixel_data = data[PXL_HEADER_BYTES:]
    total_size = len(pixel_data)
    total_packets = (total_size + chunk_size - 1) // chunk_size

    packets = []
    for i in range(total_packets):
        offset = i * chunk_size
        chunk = pixel_data[offset:offset + chunk_size]
        chunk_b64 = base64.b64encode(chunk).decode('ascii')
        packets.append({
            "format": "pxl_chunk",
            "width": width,
            "height": height,
            "frame_count": frame_count,
            "frame_interval": frame_interval,
            "flags": flags,
            "packet_index": i,
            "total_packets": total_packets,
            "offset": offset,
            "total_size": total_size,
            "chunk_base64": chunk_b64
        })
    return packets


def send_pxl_to_esp32(pxl_path: str, host: str, port: int = DEFAULT_ESP32_PORT,
                      timeout: float = SEND_TIMEOUT, switch_mode: bool = True) -> bool:
    """将.pxl文件发送到ESP32"""
    pxl_path = Path(pxl_path)
    if not pxl_path.exists():
        raise FileNotFoundError(f"文件不存在: {pxl_path}")

    packets = pxl_to_base64_chunks(str(pxl_path))
    total_packets = len(packets)

    print(f"[PACK] 准备发送: {pxl_path.name}")
    print(f"   尺寸: {packets[0]['width']}x{packets[0]['height']}")
    print(f"   帧数: {packets[0]['frame_count']}, 间隔: {packets[0]['frame_interval']}ms")
    print(f"   总数据: {packets[0]['total_size']} bytes, 分 {total_packets} 包")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        print(f"[CONN] 连接 {host}:{port}...")
        sock.connect((host, port))

        for i, packet in enumerate(packets):
            msg = {
                "type": "pixel_data",
                "data": packet,
                "ts": int(time.time())
            }
            msg_json = json.dumps(msg, separators=(',', ':')) + '\n'
            sock.sendall(msg_json.encode('utf-8'))
            progress = (i + 1) / total_packets * 100
            print(f"   [SEND] 包 {i+1}/{total_packets} ({progress:.0f}%)")
            if i < total_packets - 1:
                time.sleep(CHUNK_SEND_DELAY)

        if switch_mode:
            time.sleep(MODE_SWITCH_DELAY)
            cmd = {
                "type": "pixel_cmd",
                "data": {"command": "play", "mode": "pixel"},
                "ts": int(time.time())
            }
            sock.sendall((json.dumps(cmd, separators=(',', ':')) + '\n').encode('utf-8'))
            print("   [CMD] 已发送切换到像素模式命令")

        print("[OK] 发送完成!")
        return True
    except socket.timeout:
        print("[ERR] 连接超时")
        return False
    except ConnectionRefusedError:
        print(f"[ERR] 连接被拒绝，请确认ESP32已连接到 {host}:{port}")
        return False
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERR] 发送失败: {e}")
        return False
    finally:
        sock.close()


def send_pixel_command(host: str, port: int, command: str, mode: str = None) -> bool:
    """发送像素显示控制命令"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CMD_TIMEOUT)
    try:
        sock.connect((host, port))
        data = {"command": command}
        if mode:
            data["mode"] = mode
        msg = {
            "type": "pixel_cmd",
            "data": data,
            "ts": int(time.time())
        }
        sock.sendall((json.dumps(msg, separators=(',', ':')) + '\n').encode('utf-8'))
        print(f"[OK] 命令已发送: {command}")
        return True
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERR] 命令发送失败: {e}")
        return False
    finally:
        sock.close()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("用法:")
        print("  python pxl_sender.py <file.pxl> <host> [port]")
        print("  python pxl_sender.py --cmd <command> <host> [port] [mode]")
        sys.exit(1)
    if sys.argv[1] == '--cmd':
        cmd = sys.argv[2]
        host = sys.argv[3]
        port = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_ESP32_PORT
        mode = sys.argv[5] if len(sys.argv) > 5 else None
        send_pixel_command(host, port, cmd, mode)
    else:
        pxl_file = sys.argv[1]
        host = sys.argv[2]
        port = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_ESP32_PORT
        send_pxl_to_esp32(pxl_file, host, port)
