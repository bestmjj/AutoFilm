from asyncio import to_thread, Semaphore, TaskGroup, Lock
from os import PathLike
from pathlib import Path, PurePosixPath
from hashlib import sha256
from json import dumps, loads
from uuid import uuid4
from re import compile as re_compile

from aiofile import async_open

from app.core import logger
from app.utils import RequestUtils
from app.extensions import VIDEO_EXTS, SUBTITLE_EXTS, IMAGE_EXTS, NFO_EXTS
from app.modules.alist import AlistClient, AlistPath
from app.core.config import settings


_RUN_LOCKS: dict[str, Lock] = {}


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
        watch_interval: int = 0,
        watch_refresh: bool = True,
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

        self.source_dir = "/" + source_dir.strip("/") if source_dir.strip("/") else "/"
        self.target_dir = Path(target_dir)
        self.watch_interval = watch_interval
        self.watch_refresh = watch_refresh
        watch_key = f"{id}|{self.client.url}|{self.source_dir}|{self.target_dir.absolute()}"
        self._watch_lock_key = watch_key
        self._watch_state_path = settings.CONFIG_DIR / "watch-state" / (
            sha256(watch_key.encode("utf-8")).hexdigest() + ".json"
        )

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

    def _read_watch_state(self) -> dict[str, dict] | None:
        """None means no valid baseline exists yet."""
        try:
            data = loads(self._watch_state_path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("files"), dict):
                raise ValueError("invalid watch state")
            return data["files"]
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(f"监控状态读取失败，将重新建立基线：{exc}")
            return None

    async def _save_watch_state(self, files: dict[str, dict]) -> None:
        """Atomically checkpoint a complete successful scan in mounted /config."""
        state_path = self._watch_state_path
        await to_thread(state_path.parent.mkdir, parents=True, exist_ok=True)
        temporary = state_path.with_name(state_path.name + "." + uuid4().hex + ".tmp")
        try:
            await to_thread(
                temporary.write_text,
                dumps({"version": 1, "files": files}, ensure_ascii=False),
                encoding="utf-8",
            )
            await to_thread(temporary.replace, state_path)
        finally:
            if temporary.exists():
                await to_thread(temporary.unlink)

    async def run(self, watch_mode: bool = False) -> None:
        """
        Scan the configured root and every nested directory.

        Monitoring writes new/changed files, maintains a persistent baseline,
        and NEVER performs deletion sync (including during API failures).
        """
        lock = _RUN_LOCKS.setdefault(self._watch_lock_key, Lock())
        async with lock:
            await self._run_once(watch_mode=watch_mode)

    async def _run_once(self, watch_mode: bool = False) -> None:
        previous_files = self._read_watch_state() if watch_mode else None
        scanned_files: dict[str, dict] = {}
        scheduled_count = 0
        # Flattening or multiple formats can collide at one .strm target.
        reserved_destinations: dict[Path, str] = {}

        def filter(path: AlistPath, full_path: str) -> bool:
            nonlocal scheduled_count
            if path.is_dir or path.suffix.lower() not in self.process_file_exts:
                return False

            try:
                local_path = self.__get_local_path(path, full_path)
            except (OSError, ValueError) as exc:
                logger.warning(f"跳过无效的远端路径 {full_path}: {exc}")
                return False

            other_source = reserved_destinations.setdefault(local_path, full_path)
            if other_source != full_path:
                logger.warning(f"STRM 路径冲突：{full_path} 和 {other_source} 均映射到 {local_path}；跳过后者")
                return False
            self.processed_local_paths.add(local_path)

            changed = False
            if watch_mode:
                fingerprint = {
                    "size": path.size,
                    "modified": path.modified,
                    "hashinfo": path.hashinfo,
                    "hash_info": path.hash_info,
                    "sign": path.sign,
                }
                scanned_files[full_path] = fingerprint
                changed = previous_files is not None and previous_files.get(full_path) != fingerprint

            if not self.overwrite and local_path.exists() and not changed:
                if path.suffix.lower() in self.download_exts:
                    stat = local_path.stat()
                    if (path.modified and stat.st_mtime < path.modified_timestamp) or stat.st_size < path.size:
                        scheduled_count += 1
                        return True
                return False

            scheduled_count += 1
            return True

        logger.info(f"开始处理 {self.id} (增量监控={watch_mode})")
        if self.mode not in ("AlistURL", "RawURL", "AlistPath"):
            logger.warning(f"未知模式 {self.mode}，使用 AlistURL")
            self.mode = "AlistURL"

        self.processed_local_paths: set[Path] = set()
        async with TaskGroup() as tg:
            async for path in self.client.iter_path(
                dir_path=self.source_dir,
                wait_time=self.wait_time,
                is_detail=self.mode == "RawURL",
                filter=filter,
                refresh=watch_mode and self.watch_refresh,
            ):
                # Each task owns its path; never read a shared mutable field.
                tg.create_task(self.__file_processer(path, path.full_path))

        # A failed API call or write aborts the TaskGroup and skips checkpoint.
        if watch_mode:
            await self._save_watch_state(scanned_files)
            if self.sync_server:
                logger.info("监控模式仅补建/更新，不进行本地删除；完整同步请单独执行")
        elif self.sync_server:
            await self.__cleanup_local_files()

        logger.info(f"{self.id} 处理完成：处理 {scheduled_count} 个文件")

    async def __file_processer(self, path: AlistPath, full_path: str) -> None:
        """Write a STRM atomically or download an enabled supporting file."""
        async with self.__max_workers:
            local_path = self.__get_local_path(path, full_path)
            if self.mode == "AlistURL":
                content = path.download_url
            elif self.mode == "RawURL":
                content = path.raw_url
            elif self.mode == "AlistPath":
                content = path.abs_path
            else:
                raise ValueError(f"未知 Strm 模式 {self.mode}")

            await to_thread(local_path.parent.mkdir, parents=True, exist_ok=True)
            if local_path.suffix == ".strm":
                temporary = local_path.with_name(local_path.name + "." + uuid4().hex + ".tmp")
                try:
                    async with async_open(temporary, mode="w", encoding="utf-8") as file:
                        await file.write(content)
                    await to_thread(temporary.replace, local_path)
                finally:
                    if temporary.exists():
                        await to_thread(temporary.unlink)
                logger.info(f"{local_path} 创建/更新成功")
            else:
                async with self.__max_downloaders:
                    await RequestUtils.download(path.download_url, local_path)
                logger.info(f"{local_path} 下载成功")

    def __get_local_path(self, path: AlistPath, full_path: str) -> Path:
        """Resolve a remote file below source_dir without escaping target_dir."""
        remote = PurePosixPath(full_path)
        if not full_path.startswith("/") or ".." in remote.parts:
            raise ValueError("invalid remote absolute path")
        try:
            relative = remote.relative_to(PurePosixPath(self.source_dir))
        except ValueError as exc:
            raise ValueError("remote path outside configured source directory") from exc
        if not relative.parts:
            raise ValueError("remote path cannot be root itself")
        if self.flatten_mode:
            relative = PurePosixPath(path.name)
            if ".." in relative.parts or len(relative.parts) != 1:
                raise ValueError("invalid flat file name")
        local_path = self.target_dir.joinpath(*relative.parts)
        if path.suffix.lower() in VIDEO_EXTS:
            local_path = local_path.with_suffix(".strm")
        if not local_path.resolve().is_relative_to(self.target_dir.resolve()):
            raise ValueError("local path escapes output directory")
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


async def alist2strm():
    """
    执行所有配置的 Alist2Strm 任务
    """
    from app.core.config import settings
    
    for server in settings.AlistServerList:
        server_id = server.get("id", "未命名")
        try:
            logger.info(f"开始执行 Alist2Strm {server_id} 任务")
            await Alist2Strm(**server).run()
            logger.info(f"Alist2Strm {server_id} 任务完成")
        except Exception as e:
            logger.error(f"Alist2Strm {server_id} 任务出错: {str(e)}")
            # 继续执行其他任务，而不是直接失败