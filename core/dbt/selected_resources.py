from typing import Any, Set

# 进程级共享选择结果，供 Jinja 上下文及 defer 关系选择读取，并非调用级隔离。
SELECTED_RESOURCES = []


def set_selected_resources(selected_resources: Set[Any]) -> None:
    # 同进程独立调用可能互相覆盖；一次 build 内的工作线程共享同一次选择结果。
    global SELECTED_RESOURCES
    SELECTED_RESOURCES = list(selected_resources)
