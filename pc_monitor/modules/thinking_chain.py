"""
思考链可视化追踪器
从 OTLP spans 中提取 AI Agent 推理步骤，发送到 ESP32 桌面宠物显示

功能:
- 追踪 agent 的 thinking/tool_call/reasoning 步骤
- 生成紧凑状态消息发送到 ESP32
- 支持状态: idle → thinking → tool_call → responding → done
"""

import time
import logging
import json
import socket
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ThinkingState(Enum):
    """思考状态枚举"""
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    RESPONDING = "responding"
    ERROR = "error"
    DONE = "done"


@dataclass
class ThinkingStep:
    """单个思考步骤"""
    step_id: str
    name: str
    state: ThinkingState
    detail: str = ""
    start_time: float = 0.0
    duration_ms: float = 0.0
    tool_name: str = ""
    status: str = ""  # OK/ERROR


class ThinkingChainTracker:
    """
    思考链追踪器
    
    用法:
        tracker = ThinkingChainTracker(esp32_host="192.168.1.100")
        tracker.on_span(otlp_span)  # 从 OTLP 回调中调用
    """
    
    # span name → state 映射
    _SPAN_STATE_MAP = {
        "think": ThinkingState.THINKING,
        "thinking": ThinkingState.THINKING,
        "reasoning": ThinkingState.THINKING,
        "plan": ThinkingState.THINKING,
        "tool_call": ThinkingState.TOOL_CALL,
        "tool": ThinkingState.TOOL_CALL,
        "function_call": ThinkingState.TOOL_CALL,
        "respond": ThinkingState.RESPONDING,
        "response": ThinkingState.RESPONDING,
        "generate": ThinkingState.RESPONDING,
    }
    
    def __init__(self, esp32_host: str = "", esp32_port: int = 19876):
        self._esp32_host = esp32_host
        self._esp32_port = esp32_port
        self._current_state = ThinkingState.IDLE
        self._steps: List[ThinkingStep] = []
        self._trace_id: str = ""
        self._last_update: float = 0.0
        self._debounce_ms: float = 200.0  # 防抖间隔
        self._sock: Optional[socket.socket] = None
    
    def set_esp32(self, host: str, port: int = 19876):
        """设置 ESP32 连接参数"""
        self._esp32_host = host
        self._esp32_port = port
    
    def on_span(self, span) -> None:
        """
        处理 OTLP span (从 OTLPReceiver 回调中调用)
        
        Args:
            span: OTLPSpan 对象
        """
        # 判断是否为 agent 相关 span
        if not self._is_agent_span(span):
            return
        
        # 解析状态
        state = self._classify_span(span)
        detail = self._extract_detail(span)
        tool_name = span.attributes.get("tool.name", "")
        
        # 追踪 trace_id (同一 trace 下的步骤)
        if span.trace_id != self._trace_id:
            self._steps.clear()
            self._trace_id = span.trace_id
        
        step = ThinkingStep(
            step_id=span.span_id,
            name=span.name,
            state=state,
            detail=detail,
            start_time=span.start_time,
            duration_ms=span.duration_ms,
            tool_name=tool_name,
            status=span.status_code
        )
        self._steps.append(step)
        
        # 更新当前状态
        self._current_state = state
        
        # 发送到 ESP32 (防抖)
        now = time.time() * 1000
        if now - self._last_update >= self._debounce_ms:
            self._send_to_esp32(step)
            self._last_update = now
        
        logger.debug(f"[Thinking] {state.value}: {span.name} ({span.duration_ms:.0f}ms)")
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前思考状态摘要"""
        return {
            "state": self._current_state.value,
            "trace_id": self._trace_id,
            "step_count": len(self._steps),
            "last_step": self._steps[-1].name if self._steps else "",
            "last_tool": self._steps[-1].tool_name if self._steps and self._steps[-1].tool_name else "",
        }
    
    def reset(self):
        """重置追踪状态"""
        self._current_state = ThinkingState.IDLE
        self._steps.clear()
        self._trace_id = ""
        self._send_to_esp32(ThinkingStep(
            step_id="", name="idle", state=ThinkingState.IDLE
        ))
    
    def _is_agent_span(self, span) -> bool:
        """判断是否为 agent 推理相关 span"""
        # 通过 service name 或 span name 判断
        agent_keywords = ["agent", "llm", "tool", "think", "reason", "plan", "respond"]
        name_lower = span.name.lower()
        service_lower = span.service_name.lower()
        return any(kw in name_lower or kw in service_lower for kw in agent_keywords)
    
    def _classify_span(self, span) -> ThinkingState:
        """将 span 分类为思考状态"""
        name_lower = span.name.lower()
        for keyword, state in self._SPAN_STATE_MAP.items():
            if keyword in name_lower:
                return state
        
        # 通过属性判断
        if span.attributes.get("tool.name"):
            return ThinkingState.TOOL_CALL
        if span.status_code == "ERROR":
            return ThinkingState.ERROR
        
        return ThinkingState.THINKING
    
    def _extract_detail(self, span) -> str:
        """从 span 中提取详情文本"""
        # 优先取 attributes 中的描述
        for key in ("description", "message", "input", "tool.input"):
            if key in span.attributes:
                val = str(span.attributes[key])
                return val[:32]  # ESP32 屏幕宽度有限
        
        # 取事件中的信息
        if span.events:
            last_event = span.events[-1]
            return last_event.get("name", "")[:32]
        
        return span.name[:32]
    
    def _send_to_esp32(self, step: ThinkingStep) -> None:
        """发送思考状态到 ESP32"""
        if not self._esp32_host:
            return
        
        msg = {
            "type": "thinking_status",
            "state": step.state.value,
            "name": step.name[:24],
            "detail": step.detail[:32],
            "tool": step.tool_name[:16] if step.tool_name else "",
            "duration_ms": int(step.duration_ms),
            "step_count": len(self._steps),
        }
        
        try:
            self._send_framed(json.dumps(msg))
        except Exception as e:
            logger.warning(f"[Thinking] Failed to send to ESP32: {e}")
    
    def _send_framed(self, json_str: str) -> None:
        """使用长度前缀帧协议发送 (与 CommManager 一致)"""
        if not self._sock:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(3.0)
                self._sock.connect((self._esp32_host, self._esp32_port))
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                logger.debug(f"[Thinking] 连接ESP32失败: {e}")
                self._sock = None
                return
        
        payload = json_str.encode("utf-8")
        header = f"LEN:{len(payload)}\n".encode("utf-8")
        self._sock.sendall(header + payload)
    
    def close(self):
        """关闭连接"""
        if self._sock:
            try:
                self._sock.close()
            except Exception as e:
                logger.debug(f"关闭socket异常: {e}")
            self._sock = None


# ============ 独立测试 ============
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    tracker = ThinkingChainTracker()
    print(f"Status: {tracker.get_current_status()}")
    print("ThinkingChainTracker module loaded OK")
