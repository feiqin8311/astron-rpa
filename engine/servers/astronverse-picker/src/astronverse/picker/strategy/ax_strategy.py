"""macOS AX 策略模块"""

from astronverse.picker import IElement
from astronverse.picker.engines.ax_picker import ax_picker
from astronverse.picker.strategy.types import StrategySvc


def ax_default_strategy(service_context, strategy, strategy_svc: StrategySvc) -> IElement:
    """macOS AX 默认策略"""
    ele = ax_picker.get_element(
        start_el=strategy_svc.start_control,
        point=strategy_svc.last_point,
    )
    return ele
