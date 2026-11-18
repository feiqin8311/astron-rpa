import base64
import hashlib
import io
import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import requests
from astronverse.vision_picker.core.cv_match import AnchorMatch
from astronverse.vision_picker.logger import logger
from PIL import Image

current_directory = os.getcwd()
match_filepath = os.path.join(current_directory, "imgs", "match_img.png")


class IRectHandler(ABC):
    @staticmethod
    @abstractmethod
    def get_foreground_window_rect():
        pass


class IPickCore(ABC):
    @staticmethod
    @abstractmethod
    def get_mouse_position():
        pass

    @staticmethod
    def screenshot(region=None):
        """macOS Retina: pyautogui.screenshot is physical pixels; mouse coords are points."""
        img = pyautogui.screenshot(region=region)
        if region is None:
            target_size = pyautogui.size()
        else:
            target_size = (region[2], region[3])
        if img.size != target_size:
            img = img.resize(target_size)
        return img

    @staticmethod
    def image_to_base64(img):
        """
        将图像转为base64
        :param img: 输入图像
        :return:
        """
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")  # convert to bytes
        img_byte_arr = img_byte_arr.getvalue()  # convert bytes to base64
        return base64.b64encode(img_byte_arr).decode("utf-8")

    @staticmethod
    def get_img(rect, desktop):
        """
        获取元素图像
        :param rect:
        :param desktop:
        :return:
        """
        return desktop.crop(rect)

    @staticmethod
    def json_res(target_img, target_rect, anchor_img, anchor_rect, screen):
        """
        返回拾取到的目标元素及锚点元素的json结果
        :param target_img:
        :param target_rect:
        :param anchor_img:
        :param anchor_rect:
        :return:
        """

        def encode_image(image):
            return IPickCore.image_to_base64(image) if image else ""

        def get_position(rect, index):
            return rect[index] if rect else ""

        res = {
            "version": "1",
            "type": "cv",
            "app": "",
            "path": "",
            "img": {
                "self": encode_image(target_img),
                "parent": encode_image(anchor_img),
            },
            "pos": {
                "self_x": get_position(target_rect, 0),
                "self_y": get_position(target_rect, 1),
                "parent_x": get_position(anchor_rect, 0),
                "parent_y": get_position(anchor_rect, 1),
            },
            "sr": {"screen_w": screen.width, "screen_h": screen.height},
            "picker_type": "ELEMENT",
        }

        if not (target_img or anchor_img or target_rect or anchor_rect):
            return None

        return json.dumps(res, ensure_ascii=False)

    @staticmethod
    def base64_to_image(base64_str):
        if not base64_str:
            return None

        try:
            # 解码 base64 字符串
            image_data = base64.b64decode(base64_str)
            # 将字节数据转换为图像
            image = Image.open(io.BytesIO(image_data))
            return image
        except Exception as e:
            logger.warning(f"Error converting base64 to image: {e}")
            return None

    @staticmethod
    def get_asset_cache_dir() -> Path:
        cache_dir = Path.home() / ".astronverse" / "cache" / "assets"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def get_url(cls, input_url: str, remote_addr: str) -> str:
        """Fetch remote resource with local cache-first strategy.
        Returns base64 encoded string.
        """
        if not input_url:
            return ""

        # Normalize URL
        if input_url.startswith("http://") or input_url.startswith("https://"):
            full_url = input_url
        else:
            base = (remote_addr or "").rstrip("/")
            path = input_url.lstrip("/")
            full_url = f"{base}/{path}"

        # Hash URL for local cache key
        cache_key = hashlib.sha256(full_url.encode("utf-8")).hexdigest()
        cache_file = cls.get_asset_cache_dir() / f"{cache_key}.bin"

        # Check local cache first
        if cache_file.exists() and cache_file.stat().st_size > 0:
            try:
                content = cache_file.read_bytes()
                return base64.b64encode(content).decode("utf-8")
            except Exception as e:
                logger.warning(f"读取本地资源缓存失败 ({cache_file}): {e}")

        # Fetch from remote server
        logger.info(f"请求开始 {full_url}")
        try:
            response = requests.get(full_url, timeout=15)
            response.raise_for_status()  # 自动抛出HTTP错误
        except requests.exceptions.RequestException as e:
            raise Exception(f"服务器错误: {e}")

        content = response.content
        # Save to local cache
        try:
            cache_file.write_bytes(content)
        except Exception as e:
            logger.warning(f"写入本地资源缓存失败 ({cache_file}): {e}")

        base64_encoded_data = base64.b64encode(content).decode("utf-8")
        return base64_encoded_data

    @classmethod
    def resolve_image(cls, img_ref: str, remote_addr: str) -> str:
        """Resolve an image reference (local file, remote API url, or raw base64) to base64."""
        if not img_ref:
            return ""

        # 1. Local file path check
        if os.path.isfile(img_ref):
            try:
                return base64.b64encode(Path(img_ref).read_bytes()).decode("utf-8")
            except Exception as e:
                logger.warning(f"读取本地图像文件失败 ({img_ref}): {e}")

        # 2. Remote URL check (/api/... or http://...)
        if img_ref.startswith("/api") or img_ref.startswith("http://") or img_ref.startswith("https://"):
            return cls.get_url(img_ref, remote_addr)

        # 3. Already a base64 string or data-uri
        if img_ref.startswith("data:image"):
            comma_idx = img_ref.find(",")
            if comma_idx != -1:
                return img_ref[comma_idx + 1 :]
        return img_ref

    @staticmethod
    def match_imgs(data, remote_addr, canny_flag=False):
        match = AnchorMatch()

        target = data["img"]["self"]
        anchor = data["img"]["parent"]
        match_similarity = data.get("similarity", 0.60)

        target = IPickCore.resolve_image(target, remote_addr)
        logger.debug("获取到目标图像base64（长度：{}）".format(len(target) if target else 0))

        target_img = IPickCore.base64_to_image(target)
        center_coords_aim = f"{data['pos']['self_x']},{data['pos']['self_y']}"

        if anchor:
            anchor = IPickCore.resolve_image(anchor, remote_addr)
            logger.debug("获取到锚点图像base64（长度：{}）".format(len(anchor) if anchor else 0))
            anchor_img = IPickCore.base64_to_image(anchor)
            center_coords_anchor = f"{data['pos']['parent_x']},{data['pos']['parent_y']}"
        else:
            anchor_img = None
            center_coords_anchor = ""

        if sys.platform == "darwin":
            match_img = IPickCore.screenshot(region=None)
        else:
            match_img = pyautogui.screenshot(region=None)
        match_img.save(match_filepath)
        ratio_w = match_img.width / data["sr"]["screen_w"]
        ratio_h = match_img.height / data["sr"]["screen_h"]
        ratio = f"{ratio_w},{ratio_h}"
        match_img = np.array(match_img)
        try:
            _, match_box = match.process_image(
                match_img,
                target_img,
                anchor_img,
                center_coords_aim=center_coords_aim,
                center_coords_anchor=center_coords_anchor,
                canny_flag=canny_flag,
                ratio=ratio,
                match_similarity=match_similarity,
            )
        except cv2.error:
            match_box = None
        return match_box
