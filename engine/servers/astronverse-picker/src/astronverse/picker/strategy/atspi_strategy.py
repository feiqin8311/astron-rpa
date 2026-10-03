"""Linux AT-SPI 策略模块"""

from astronverse.picker import IElement
from astronverse.picker.engines.atspi_picker import atspi_picker
from astronverse.picker.strategy.types import StrategySvc


def atspi_default_strategy(service_context, strategy, strategy_svc: StrategySvc) -> IElement:
    """Linux AT-SPI 默认策略"""
    ele = atspi_picker.get_element(
        start_el=strategy_svc.start_control,
        point=strategy_svc.last_point,
    )
    return ele
