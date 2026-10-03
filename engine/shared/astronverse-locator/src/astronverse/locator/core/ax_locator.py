import dataclasses
from collections.abc import Generator
from copy import deepcopy
from typing import Any, Optional, Union

from astronverse.baseline.logger.logger import logger
from astronverse.locator import ILocator, PickerType, Rect
from astronverse.locator.core import ax_common


class AXLocator(ILocator):
    """macOS Accessibility 定位器"""

    def __init__(self, element: Any):
        self._element = element
        self._rect: Optional[Rect] = None

    def rect(self) -> Optional[Rect]:
        if self._rect is None:
            self._rect = ax_common.ax_rect(self._element)
        return self._rect

    def control(self) -> Any:
        return ax_common.AXControl(self._element)


@dataclasses.dataclass
class AXNode:
    """前端 PATH 节点解析后的数据结构"""

    tag_name: Optional[str] = None
    checked: bool = True
    disable_keys: list[str] = dataclasses.field(default_factory=list)
    cls: Optional[str] = None
    index: Optional[int] = None
    name: Optional[str] = None
    value: Optional[str] = None
    identifier: Optional[str] = None


class AXEle:
    """用于与 AXNode 比较的 AX 元素包装类，记录比较状态与匹配得分"""

    def __init__(self, element: Any, index: Optional[int] = None, index_match_sort: str = ""):
        self.element = element
        self._rect: Optional[Rect] = None
        self._index: Optional[int] = index
        self._cls: Optional[str] = None
        self._name: Optional[str] = None
        self._tag_name: Optional[str] = None
        self._value: Optional[str] = None
        self._identifier: Optional[str] = None

        self.index_parent_match_sort: str = ""
        self.index_match_sort: str = index_match_sort

    @property
    def rect(self) -> Optional[Rect]:
        if self._rect is None:
            self._rect = ax_common.ax_rect(self.element)
        return self._rect

    @property
    def tag_name(self) -> str:
        if self._tag_name is None:
            self._tag_name = ax_common.ax_attr(self.element, "AXRole") or ""
        return self._tag_name

    @property
    def cls(self) -> str:
        if self._cls is None:
            self._cls = ax_common.ax_attr(self.element, "AXSubrole") or ""
        return self._cls

    @property
    def name(self) -> str:
        if self._name is None:
            self._name = (
                ax_common.ax_attr(self.element, "AXTitle")
                or ax_common.ax_attr(self.element, "AXDescription")
                or ax_common.ax_attr(self.element, "AXHelp")
                or ""
            )
        return self._name

    @property
    def value(self) -> Optional[str]:
        if self._value is None:
            val = ax_common.ax_attr(self.element, "AXValue")
            if val is not None and isinstance(val, (str, int, float)):
                self._value = str(val)
            else:
                self._value = ""
        return self._value or None

    @property
    def identifier(self) -> str:
        if self._identifier is None:
            self._identifier = ax_common.ax_attr(self.element, "AXIdentifier") or ""
        return self._identifier

    @property
    def index(self) -> int:
        return self._index if self._index is not None else 0


class AXFactory:
    """macOS Accessibility 定位器工厂"""

    @classmethod
    def _parse_node(cls, path: dict) -> AXNode:
        return AXNode(
            tag_name=path.get("tag_name"),
            checked=path.get("checked", True),
            disable_keys=path.get("disable_keys") or [],
            cls=path.get("cls"),
            index=path.get("index"),
            name=path.get("name"),
            value=path.get("value"),
            identifier=path.get("identifier"),
        )

    @classmethod
    def __compare_node_and_ax_ele__(cls, ax_ele: AXEle, node: AXNode, keys: list[str]) -> bool:
        if not node.checked:
            return True

        for key in keys:
            if key in node.disable_keys:
                continue
            v1 = getattr(node, key, None)
            v2 = getattr(ax_ele, key, None)
            if v1 is not None:
                v1 = str(v1)
            if v2 is not None:
                v2 = str(v2)
            if not v1 and not v2:
                continue
            if v1 != v2:
                return False
        return True

    @classmethod
    def __get_child_walk_ele__(cls, parent_element: Any) -> Generator[AXEle, None, None]:
        children = ax_common.ax_children(parent_element)
        role_counters: dict[str, int] = {}
        for child in children:
            r = ax_common.ax_attr(child, "AXRole") or ""
            idx = role_counters.get(r, 0)
            role_counters[r] = idx + 1
            yield AXEle(element=child, index=idx)

    @classmethod
    def __find_candidate_windows__(cls, app_pids: list[int], root_node: AXNode) -> list[tuple[Any, int]]:
        candidates = []
        for pid in app_pids:
            app_el = ax_common.app_element(pid)
            if not app_el:
                continue
            wins = ax_common.app_windows(app_el)
            for w in wins:
                if "tag_name" not in root_node.disable_keys and root_node.tag_name:
                    w_tag = ax_common.ax_attr(w, "AXRole") or ""
                    if w_tag != root_node.tag_name:
                        continue
                if "cls" not in root_node.disable_keys and root_node.cls:
                    w_cls = ax_common.ax_attr(w, "AXSubrole") or ""
                    if w_cls != root_node.cls:
                        continue
                w_name = (
                    ax_common.ax_attr(w, "AXTitle")
                    or ax_common.ax_attr(w, "AXDescription")
                    or ax_common.ax_attr(w, "AXHelp")
                    or ""
                )
                candidates.append((w, pid, str(w_name)))

        if not candidates:
            return []

        target_name = root_node.name
        if "name" in root_node.disable_keys or not target_name:
            matched = [(c[0], c[1]) for c in candidates]
        else:
            # 1. 尝试精确匹配
            exact = [c for c in candidates if c[2] == target_name]
            if exact:
                matched = [(c[0], c[1]) for c in exact]
            else:
                # 2. contains fallback (最长 name 匹配)
                contains = [c for c in candidates if target_name in c[2] or c[2] in target_name]
                if contains:
                    contains.sort(key=lambda c: len(c[2]), reverse=True)
                    best_name = contains[0][2]
                    matched = [(c[0], c[1]) for c in contains if c[2] == best_name]
                else:
                    matched = []

        # 3. 如果启用了 index，对匹配结果排序让匹配 index 的窗口优先
        if matched and "index" not in root_node.disable_keys and root_node.index is not None:

            def _get_idx(item):
                w, pid = item
                app_el = ax_common.app_element(pid)
                wins = ax_common.app_windows(app_el)
                w_name = (
                    ax_common.ax_attr(w, "AXTitle")
                    or ax_common.ax_attr(w, "AXDescription")
                    or ax_common.ax_attr(w, "AXHelp")
                    or ""
                )
                same_name = [
                    x
                    for x in wins
                    if (
                        ax_common.ax_attr(x, "AXTitle")
                        or ax_common.ax_attr(x, "AXDescription")
                        or ax_common.ax_attr(x, "AXHelp")
                        or ""
                    )
                    == w_name
                ]
                for i, x in enumerate(same_name):
                    if ax_common._is_same_element(x, w):
                        return i
                return 0

            matched.sort(key=lambda item: 0 if _get_idx(item) == root_node.index else 1)

        return matched

    @classmethod
    def __find_one__(cls, ele: dict, picker_type: str, **kwargs) -> Optional[AXLocator]:
        app_name = ele.get("app", "")
        bundle_id = ele.get("bundle_id")
        path_list = ele.get("path", [])
        if not path_list:
            return None

        # a. 候选 apps
        app_pids = ax_common.find_apps(app_name, bundle_id)
        if not app_pids:
            raise Exception("元素无法找到")

        node_list = [cls._parse_node(p) for p in path_list]
        root_node = node_list[0]

        # e. path[0] 是 AXApplication (如菜单栏等)
        if root_node.tag_name == "AXApplication":
            for pid in app_pids:
                app_el = ax_common.app_element(pid)
                if not app_el:
                    continue
                app = ax_common.running_app(pid)
                if app:
                    try:
                        from AppKit import NSApplicationActivateIgnoringOtherApps

                        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    except Exception:
                        pass

                if picker_type == PickerType.WINDOW.value or len(node_list) == 1:
                    return AXLocator(app_el)

                search_list = [AXEle(element=app_el, index=0, index_match_sort="1")]
                element_found = True
                i = 0
                for i, node in enumerate(node_list[1:]):
                    child_list = []
                    for search in search_list:
                        for ax_ele in cls.__get_child_walk_ele__(search.element):
                            ax_ele.index_parent_match_sort = search.index_match_sort
                            child_list.append(ax_ele)
                    child_list = [
                        item
                        for item in child_list
                        if cls.__compare_node_and_ax_ele__(
                            item, node, ["tag_name", "name", "cls", "value", "identifier"]
                        )
                    ]
                    for item in child_list:
                        idx_match = cls.__compare_node_and_ax_ele__(item, node, ["index"])
                        item.index_match_sort = f"{item.index_parent_match_sort}{'1' if idx_match else '0'}"
                    search_list = child_list
                    if not search_list:
                        element_found = False
                        break

                if element_found and search_list and i == (len(node_list) - 2):
                    search_list.sort(key=lambda s: -int(s.index_match_sort) if s.index_match_sort else 0)
                    match = search_list[0]
                    return AXLocator(match.element)

            raise Exception("元素无法找到")

        # b. 候选 windows
        candidate_windows = cls.__find_candidate_windows__(app_pids, root_node)
        if not candidate_windows:
            raise Exception("元素无法找到")

        if picker_type == PickerType.WINDOW.value:
            chosen_win, chosen_pid = candidate_windows[0]
            ax_common.raise_window(chosen_win, chosen_pid)
            return AXLocator(chosen_win)

        # c. 逐层广度优先匹配
        for win, pid in candidate_windows:
            try:
                ax_common.raise_window(win, pid)
                if len(node_list) == 1:
                    return AXLocator(win)

                search_list = [AXEle(element=win, index=0, index_match_sort="1")]
                element_found = True
                i = 0
                for i, node in enumerate(node_list[1:]):
                    child_list = []
                    for search in search_list:
                        for ax_ele in cls.__get_child_walk_ele__(search.element):
                            ax_ele.index_parent_match_sort = search.index_match_sort
                            child_list.append(ax_ele)
                    child_list = [
                        item
                        for item in child_list
                        if cls.__compare_node_and_ax_ele__(
                            item, node, ["tag_name", "name", "cls", "value", "identifier"]
                        )
                    ]
                    for item in child_list:
                        idx_match = cls.__compare_node_and_ax_ele__(item, node, ["index"])
                        item.index_match_sort = f"{item.index_parent_match_sort}{'1' if idx_match else '0'}"
                    search_list = child_list
                    if not search_list:
                        element_found = False
                        break

                if element_found and search_list and i == (len(node_list) - 2):
                    search_list.sort(key=lambda s: -int(s.index_match_sort) if s.index_match_sort else 0)
                    match = search_list[0]
                    return AXLocator(match.element)
            except Exception as e:
                logger.debug(f"Candidate window search error: {e}")
                continue

        raise Exception("元素无法找到")

    @classmethod
    def __find_similar__(cls, ele: dict, picker_type: str, **kwargs) -> Optional[list[AXLocator]]:
        path_list = ele.get("path", [])
        if not path_list:
            return None

        # 1. 查找父路径
        parent_path = [v for v in path_list if v.get("similar_parent", False)]
        if not parent_path:
            return None

        parent_ele = deepcopy(ele)
        parent_ele["path"] = parent_path
        parent_locator = cls.__find_one__(parent_ele, picker_type=picker_type, **kwargs)
        if not parent_locator:
            raise Exception("元素无法找到")

        # 2. 查找子元素
        node_list = [cls._parse_node(path) for path in path_list if not path.get("similar_parent", False)]
        if not node_list:
            return []

        parent_element = getattr(parent_locator, "_element", None)
        if parent_element is None:
            ctrl = parent_locator.control()
            parent_element = getattr(ctrl, "_element", None)

        res = []
        for root_child in cls.__get_child_walk_ele__(parent_element):
            is_ok = cls.__compare_node_and_ax_ele__(
                root_child, node_list[0], ["tag_name", "name", "cls", "value", "identifier"]
            )
            if not is_ok:
                continue

            if len(node_list) == 1:
                res.append(AXLocator(root_child.element))
                continue
            else:
                search_list = [root_child]
                i = 0
                for i, node in enumerate(node_list[1:]):
                    child_list = []
                    for search in search_list:
                        for ax_ele in cls.__get_child_walk_ele__(search.element):
                            ax_ele.index_parent_match_sort = search.index_match_sort
                            child_list.append(ax_ele)
                    child_list = [
                        item
                        for item in child_list
                        if cls.__compare_node_and_ax_ele__(
                            item, node, ["tag_name", "name", "cls", "value", "identifier"]
                        )
                    ]
                    for item in child_list:
                        idx_match = cls.__compare_node_and_ax_ele__(item, node, ["index"])
                        item.index_match_sort = f"{item.index_parent_match_sort}{'1' if idx_match else '0'}"
                    search_list = child_list
                    if not search_list:
                        break

                if not search_list or i != (len(node_list) - 2):
                    continue
                search_list.sort(key=lambda s: -int(s.index_match_sort) if s.index_match_sort else 0)
                match = search_list[0]
                res.append(AXLocator(match.element))

        return res

    @classmethod
    def find(cls, ele: dict, picker_type: str, **kwargs) -> Union[list[AXLocator], AXLocator, None]:
        if picker_type == PickerType.SIMILAR.value:
            return cls.__find_similar__(ele, picker_type, **kwargs)
        else:
            return cls.__find_one__(ele, picker_type, **kwargs)


ax_factory = AXFactory()
