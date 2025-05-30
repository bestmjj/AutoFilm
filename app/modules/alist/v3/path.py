from re import sub
from typing import Any
from datetime import datetime
from pydantic import BaseModel
from app.utils import URLUtils

class AlistPath(BaseModel):
    """
    Alist 文件/目录对象
    """
    server_url: str  # 服务器地址
    base_path: str  # 基础路径（用于计算文件/目录在 Alist 服务器上的绝对地址）
    file_path: str  # 文件/目录路径（之前是 _path）
    name: str  # 文件/目录名称
    size: int  # 文件大小
    is_dir: bool  # 是否为目录
    modified: str = ""  # 修改时间
    created: str = ""  # 创建时间
    sign: str = ""  # 签名
    thumb: str = ""  # 缩略图
    type: int = 0  # 类型
    hashinfo: str = "null"  # 哈希信息（字符串）
    hash_info: dict | None = None  # 哈希信息（键值对）
    raw_url: str = ""  # 原始地址
    readme: str = ""  # Readme 地址
    header: str = ""  # 头部信息
    provider: str = ""  # 提供者
    related: Any = None  # 相关信息
    full_path: str = ""  # 完整路径

    @property
    def abs_path(self) -> str:
        """
        文件/目录在 Alist 服务器上的绝对路径
        """
        return self.base_path.rstrip("/") + self.file_path

    @property
    def download_url(self) -> str:
        """
        文件下载地址
        """
        if self.sign:
            url = self.server_url + "/d" + self.abs_path + "?sign=" + self.sign
        else:
            url = self.server_url + "/d" + self.abs_path
        return URLUtils.encode(url)

    @property
    def proxy_download_url(self) -> str:
        """
        Alist代理下载地址
        """
        return sub(r"/d/", "/p/", self.download_url, 1)

    @property
    def suffix(self) -> str:
        """
        文件后缀
        """
        if self.is_dir:
            return ""
        else:
            return "." + self.name.split(".")[-1]

    def __parse_timestamp(self, time_str: str) -> float:
        """
        解析时间字符串得到时间的时间戳
        """
        dt = datetime.fromisoformat(time_str)
        return dt.timestamp()

    @property
    def modified_timestamp(self) -> float:
        """
        获得修改时间的时间戳
        """
        return self.__parse_timestamp(self.modified)

    @property
    def created_timestamp(self) -> float:
        """
        获得创建时间的时间戳
        """
        return self.__parse_timestamp(self.created)

