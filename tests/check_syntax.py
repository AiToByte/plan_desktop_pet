"""语法检查脚本"""
import ast
import sys
import os

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

files = [
    'tests/test_pxl_encoder.py',
    'tests/test_pxl_decoder.py', 
    'tests/test_weather.py',
    'pc_monitor/modules/weather.py',
    'pc_monitor/modules/agent_monitor.py',
    'pc_monitor/modules/communication.py',
    'pc_monitor/modules/token_stats.py',
    'pc_monitor/modules/otlp_receiver.py',
    'pc_monitor/main.py',
    'pixel_tool/pixel_tool.py',
    'pixel_tool/pxl_encoder.py',
    'pixel_tool/pxl_decoder.py',
    'pixel_tool/pxl_sender.py',
]

ok = 0
fail = 0
for f in files:
    try:
        with open(f, encoding='utf-8') as fh:
            ast.parse(fh.read())
        print(f'[OK] {f}')
        ok += 1
    except FileNotFoundError:
        print(f'[SKIP] {f} not found')
    except SyntaxError as e:
        print(f'[FAIL] {f}: {e}')
        fail += 1

print(f'\n{ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
