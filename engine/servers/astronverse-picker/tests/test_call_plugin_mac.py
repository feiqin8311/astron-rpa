from astronverse.picker.strategy.auto_strategy_mac import (
    _WebViewportControl,
    find_web_area_down,
    viewport_from_web_area,
)


class _Bound:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class _FakeAX:
    def __init__(self, role, parent=None, rect=None, pid=0, children=None):
        self.role = role
        self.parent = parent
        self._rect = rect
        self.pid = pid
        self.children = children or []
        for child in self.children:
            child.parent = self


def test_find_web_area_down_from_window():
    win = _FakeAX("AXWindow", rect=_Bound(0, 0, 800, 600), pid=1)
    group = _FakeAX("AXGroup", parent=win, rect=_Bound(0, 80, 800, 600), pid=1)
    web = _FakeAX("AXWebArea", parent=group, rect=_Bound(0, 80, 800, 600), pid=1)
    btn = _FakeAX("AXButton", parent=web, rect=_Bound(10, 100, 80, 130), pid=1)
    win.children = [group]
    group.children = [web]
    web.children = [btn]

    assert find_web_area_down(win) is web
    assert find_web_area_down(btn) is web
    viewport = viewport_from_web_area(web)
    assert isinstance(viewport, _WebViewportControl)
    assert viewport.BoundingRectangle.left == web._rect.left
    assert viewport.BoundingRectangle.top == web._rect.top
