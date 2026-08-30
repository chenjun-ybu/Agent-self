"""
ToolRegistry: 统一工具调用接口

将所有 Tool 注册到统一接口中，通过结构化请求与响应进行调用。
这是 Protocol 的具体实现——规定工具如何被发现、调用、传递结果并接受约束。
"""

from protocol import ToolCallRequest, ToolCallResponse, CallStatus
from tools import SmilesValidatorTool, UnitConverterTool, DuplicateCheckerTool
from typing import Callable


class ToolRegistry:
    """
    统一工具调用注册中心。
    每个工具通过 register() 注册，通过 call() 按名称调用。
    所有调用产生结构化 ToolCallRequest / ToolCallResponse。
    """

    def __init__(self):
        self._tools: dict[str, object] = {}
        self._call_log: list[dict] = []

    def register(self, tool) -> None:
        """注册工具到统一接口"""
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict]:
        """列出所有已注册工具（能力发现）"""
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def call(self, request: ToolCallRequest) -> ToolCallResponse:
        """
        统一调用入口。
        通过 tool_name 查找已注册的工具，执行并返回结构化响应。
        """
        if request.tool_name not in self._tools:
            response = ToolCallResponse(
                tool_name=request.tool_name,
                call_id=request.call_id,
                status=CallStatus.ERROR,
                error=f"未注册的工具: {request.tool_name}",
            )
            self._call_log.append({
                "request": request.to_dict(),
                "response": response.to_dict(),
            })
            return response

        tool = self._tools[request.tool_name]
        try:
            response = tool.execute(request)
        except Exception as e:
            response = ToolCallResponse(
                tool_name=request.tool_name,
                call_id=request.call_id,
                status=CallStatus.ERROR,
                error=f"执行异常: {e}",
            )

        self._call_log.append({
            "request": request.to_dict(),
            "response": response.to_dict(),
        })
        return response

    def call_simple(self, tool_name: str, **parameters) -> ToolCallResponse:
        """便捷调用方法"""
        req = ToolCallRequest(tool_name=tool_name, parameters=parameters)
        return self.call(req)

    def get_call_log(self) -> list[dict]:
        """获取所有调用的日志记录"""
        return self._call_log


def create_default_registry() -> ToolRegistry:
    """创建并返回包含默认工具的注册中心"""
    registry = ToolRegistry()
    registry.register(SmilesValidatorTool())
    registry.register(UnitConverterTool())
    registry.register(DuplicateCheckerTool())
    return registry
