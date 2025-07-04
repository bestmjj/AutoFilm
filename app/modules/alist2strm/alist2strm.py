from asyncio import to_thread, Semaphore, TaskGroup
from os import PathLike
from pathlib import Path
from re import compile as re_compile

from aiofile import async_open

from app.core import logger
from app.utils import RequestUtils
from app.extensions import VIDEO_EXTS, SUBTITLE_EXTS, IMAGE_EXTS, NFO_EXTS
from app.modules.alist import AlistClient, AlistPath


class Alist2Strm:
    def __init__(
        self,
        id: str = "",
        url: str = "http://localhost:5244",
        username: str = "",
        password: str = "",
        token: str = "",
        source_dir: str = "/",
        target_dir: str | PathLike = "",
        flatten_mode: bool = False,
        subtitle: bool = False,
        image: bool = False,
        nfo: bool = False,
        mode: str = "AlistURL",
        full_path: str = "/",
        overwrite: bool = False,
        other_ext: str = "",
        max_workers: int = 50,
        max_downloaders: int = 5,
        wait_time: float | int = 0,
        sync_server: bool = False,
        sync_ignore: str | None = None,
        **_,
    ) -> None:
        """
        实例化 Alist2Strm 对象

        :param url: Alist 服务器地址，默认为 "http://localhost:5244"
        :param username: Alist 用户名，默认为空
        :param password: Alist 密码，默认为空
        :param source_dir: 需要同步的 Alist 的目录，默认为 "/"
        :param target_dir: strm 文件输出目录，默认为当前工作目录
        :param flatten_mode: 平铺模式，将所有 Strm 文件保存至同一级目录，默认为 False
        :param subtitle: 是否下载字幕文件，默认为 False
        :param image: 是否下载图片文件，默认为 False
        :param nfo: 是否下载 .nfo 文件，默认为 False
        :param mode: Strm模式(AlistURL/RawURL/AlistPath)
        :param overwrite: 本地路径存在同名文件时是否重新生成/下载该文件，默认为 False
        :param sync_server: 是否同步服务器，启用后若服务器中删除了文件，也会将本地文件删除，默认为 True
        :param other_ext: 自定义下载后缀，使用西文半角逗号进行分割，默认为空
        :param max_workers: 最大并发数
        :param max_downloaders: 最大同时下载
        :param wait_time: 遍历请求间隔时间，单位为秒，默认为 0
        :param sync_ignore: 同步时忽略的文件正则表达式
        """

        self.client = AlistClient(url, username, password, token)
        self.mode = mode

        self.source_dir = source_dir
        self.target_dir = Path(target_dir)

        self.flatten_mode = flatten_mode
        if flatten_mode:
            subtitle = image = nfo = False

        download_exts: set[str] = set()
        if subtitle:
            download_exts |= SUBTITLE_EXTS
        if image:
            download_exts |= IMAGE_EXTS
        if nfo:
            download_exts |= NFO_EXTS
        if other_ext:
            download_exts |= frozenset(other_ext.lower().split(","))

        self.download_exts = download_exts
        self.process_file_exts = VIDEO_EXTS | download_exts

        self.overwrite = overwrite
        self.__max_workers = Semaphore(max_workers)
        self.__max_downloaders = Semaphore(max_downloaders)
        self.wait_time = wait_time
        self.sync_server = sync_server
        self.id = id

        if sync_ignore:
            self.sync_ignore_pattern = re_compile(sync_ignore)
        else:
            self.sync_ignore_pattern = None

    async def run(self) -> None:
        """
        处理主体
        """
        def filter(path: AlistPath, full_path: str) -> bool:
            """
            过滤器
            根据 Alist2Strm 配置判断是否需要处理该文件
            将云盘上上的文件对应的本地文件路径保存至 self.processed_local_paths
            :param path: AlistPath 对象
            :param full_path: 完整路径
            """
            
            if path.is_dir:
                return False
            if path.suffix.lower() not in self.process_file_exts:
                logger.debug(f"文件 {path.name} 不在处理列表中")
                return False
            try:
                local_path = self.__get_local_path(path, full_path)
            except OSError as e:  # 可能是文件名过长
                logger.warning(f"获取 {full_path} 本地路径失败：{e}")
                return False
            self.full_path = full_path
            self.processed_local_paths.add(local_path)
            if not self.overwrite and local_path.exists():
                if path.suffix in self.download_exts:
                    local_path_stat = local_path.stat()
                    if local_path_stat.st_mtime < path.modified_timestamp:
                        logger.debug(
                            f"文件 {local_path} 已过期，需要重新处理 {full_path}"
                        )
                        return True
                    if local_path_stat.st_size < path.size:
                        logger.debug(
                            f"文件 {local_path} 大小不一致，可能是本地文件损坏，需要重新处理 {full_path}"
                        )
                        return True
                logger.debug(f"文件 {local_path} 已存在，跳过处理 {full_path}")
                return False
            return True

        logger.info(f"开始处理 {self.id}")
        if self.mode not in ["AlistURL", "RawURL", "AlistPath"]:
            logger.warning(
                f"Alist2Strm 的模式 {self.mode} 不存在，已设置为默认模式 AlistURL"
            )
            self.mode = "AlistURL"
        if self.mode == "RawURL":
            is_detail = True
        else:
            is_detail = False
        self.processed_local_paths = set()  # 云盘文件对应的本地文件路径
        async with self.__max_workers, TaskGroup() as tg:
            async for path in self.client.iter_path(
                dir_path=self.source_dir,
                wait_time=self.wait_time,
                is_detail=is_detail,
                filter=filter,  # 传递修改后的 filter 函数
            ):
                tg.create_task(self.__file_processer(path))
                
        if self.sync_server:
            await self.__cleanup_local_files()
            logger.info("清理过期的 .strm 文件完成")
        logger.info(f"{self.id} 处理完成")
        logger.info("Alist2Strm 处理完成")

    async def __file_processer(self, path: AlistPath) -> None:
        """
        异步保存文件至本地

        :param path: AlistPath 对象
        """
        local_path = self.__get_local_path(path, self.full_path)
        if self.mode == "AlistURL":
            content = path.download_url
        elif self.mode == "RawURL":
            content = path.raw_url
        elif self.mode == "AlistPath":
            content = path.path
        else:
            raise ValueError(f"AlistStrm 未知的模式 {self.mode}")

        await to_thread(local_path.parent.mkdir, parents=True, exist_ok=True)

        logger.debug(f"开始处理 {local_path}")
        if local_path.suffix == ".strm":
            async with async_open(local_path, mode="w", encoding="utf-8") as file:
                await file.write(content)
            logger.info(f"{local_path} 创建成功")
        else:
            async with self.__max_downloaders:
                await RequestUtils.download(path.download_url, local_path)
                logger.info(f"{local_path} 下载成功")

    def __get_local_path(self, path: AlistPath, full_path: str = "") -> Path:
        """
        根据给定的 AlistPath 对象和当前的配置，计算出本地文件路径。
        :param path: AlistPath 对象
        :param full_path: 完整路径
        :return: 本地文件路径
        """
        if self.flatten_mode:
            local_path = self.target_dir / path.name
        else:
            relative_path = full_path.replace(self.source_dir, "", 1) if full_path else path.name
            if relative_path.startswith("/"):
                relative_path = relative_path[1:]
            local_path = self.target_dir / relative_path
        if path.suffix.lower() in VIDEO_EXTS:
            local_path = local_path.with_suffix(".strm")
        return local_path

    async def __cleanup_local_files(self) -> None:
        """
        删除服务器中已删除的本地的 .strm 文件及其关联文件
        如果文件后缀在 sync_ignore 中，则不会被删除
        """
        logger.info("开始清理本地文件")

        if self.flatten_mode:
            all_local_files = [f for f in self.target_dir.iterdir() if f.is_file()]
        else:
            all_local_files = [f for f in self.target_dir.rglob("*") if f.is_file()]

        files_to_delete = set(all_local_files) - self.processed_local_paths

        for file_path in files_to_delete:
            # 检查文件是否匹配忽略正则表达式
            if self.sync_ignore_pattern and self.sync_ignore_pattern.search(
                file_path.name
            ):
                logger.debug(f"文件 {file_path.name} 在忽略列表中，跳过删除")
                continue

            try:
                if file_path.exists():
                    await to_thread(file_path.unlink)
                    logger.info(f"删除文件：{file_path}")

                    # 检查并删除空目录
                    parent_dir = file_path.parent
                    while parent_dir != self.target_dir:
                        if any(parent_dir.iterdir()):
                            break  # 目录不为空，跳出循环
                        else:
                            parent_dir.rmdir()
                            logger.info(f"删除空目录：{parent_dir}")
                        parent_dir = parent_dir.parent
            except Exception as e:
                logger.error(f"删除文件 {file_path} 失败：{e}")






