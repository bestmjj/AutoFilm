from os.path import dirname
import asyncio
from sys import path
from typing import Optional

path.append(dirname(dirname(__file__)))

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type:ignore
from apscheduler.triggers.cron import CronTrigger  # type:ignore

from app.core import settings, logger
from app.extensions import LOGO
from app.modules import Alist2Strm, Ani2Alist
from app.modules.telegram_bot import TelegramBot
from app.modules.webui import app as web_app
from datetime import datetime, timedelta
import uvicorn


def print_logo() -> None:
    """
    打印 Logo
    """

    print(LOGO)
    print(f" {settings.APP_NAME} {settings.APP_VERSION} ".center(65, "="))
    print("")


# Global scheduler instance to be accessible by webui
scheduler = None


async def start_web_server():
    """
    启动Web服务器
    """
    config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    """
    主程序入口，初始化并启动所有服务
    """
    global scheduler
    
    print_logo()

    logger.info(f"AutoFilm {settings.APP_VERSION} 启动中...")
    logger.debug(f"是否开启 DEBUG 模式: {settings.DEBUG}")

    # 初始化调度器
    scheduler = AsyncIOScheduler()

    if settings.AlistServerList:
        logger.info("检测到 Alist2Strm 模块配置，正在添加至后台任务")
        for server in settings.AlistServerList:
            cron = server.get("cron")
            if cron:
                # 使用 lambda 延迟初始化，只有在执行时才创建 Alist2Strm 实例
                scheduler.add_job(
                    lambda s=server: asyncio.create_task(Alist2Strm(**s).run()), 
                    trigger=CronTrigger.from_crontab(cron)
                )
                logger.info(f"{server['id']} 已被添加至后台任务")
            else:
                logger.warning(f"{server['id']} 未设置 cron")

            watch_interval = server.get("watch_interval", 0)
            if watch_interval:
                if not isinstance(watch_interval, int) or isinstance(watch_interval, bool) or watch_interval < 60:
                    logger.warning(f"{server.get('id', '未命名')} 的 watch_interval 必须是至少 60 秒的整数")
                else:
                    async def scan_watch(s=server):
                        try:
                            await Alist2Strm(**s).run(watch_mode=True)
                        except Exception as exc:
                            logger.error(f"{s.get('id', '未命名')} OpenList 监控扫描失败：{exc}")

                    scheduler.add_job(
                        scan_watch,
                        trigger="interval",
                        seconds=watch_interval,
                        id=f"openlist-watch-{server.get('id', 'unnamed')}",
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                        next_run_time=datetime.now(),
                    )
                    logger.info(f"{server.get('id', '未命名')} 已启用 OpenList 递归监控，每 {watch_interval} 秒检查")

            after_time = server.get("after_time")
            if after_time != None:
                if after_time > 0:
                    run_time = datetime.now() + timedelta(seconds=after_time)
                    # 使用 lambda 延迟初始化，只有在执行时才创建 Alist2Strm 实例
                    scheduler.add_job(
                        lambda s=server: asyncio.create_task(Alist2Strm(**s).run()), 
                        'date', 
                        run_date=run_time
                    )
                    logger.info(f"{server['id']} 已被添加至 {after_time} 秒后执行")
    else:
        logger.warning("未检测到 Alist2Strm 模块配置")

    if settings.Ani2AlistList:
        logger.info("检测到 Ani2Alist 模块配置，正在添加至后台任务")
        for server in settings.Ani2AlistList:
            cron = server.get("cron")
            if cron:
                # 修复 Ani2Alist 的异步执行方式
                scheduler.add_job(
                    lambda s=server: asyncio.create_task(Ani2Alist(**s).run()), 
                    trigger=CronTrigger.from_crontab(cron)
                )
                logger.info(f"{server['id']} 已被添加至后台任务")
            else:
                logger.warning(f"{server['id']} 未设置 cron")

            after_time = server.get("after_time")
            if after_time != None:
                if after_time > 0:
                    run_time = datetime.now() + timedelta(seconds=after_time)
                    # 修复 Ani2Alist 的异步执行方式
                    scheduler.add_job(
                        lambda s=server: asyncio.create_task(Ani2Alist(**s).run()), 
                        'date', 
                        run_date=run_time
                    )
                    logger.info(f"{server['id']} 已被添加至 {after_time} 秒后执行")
    else:
        logger.warning("未检测到 Ani2Alist 模块配置")


    # 初始化并运行Telegram机器人（如果已配置）
    telegram_bot: Optional[TelegramBot] = None
    if hasattr(settings, 'TelegramBot') and settings.TelegramBot.get('token'):
        logger.info("检测到 Telegram Bot 配置，正在启动")
        telegram_bot = TelegramBot(**settings.TelegramBot)
        # 启动Telegram机器人
        await telegram_bot.start()
    else:
        logger.info("未检测到 Telegram Bot 配置")

    scheduler.start()
    logger.info("AutoFilm 启动完成")

    # 启动Web服务器作为后台任务
    web_task = asyncio.create_task(start_web_server())

    try:
        # 保持程序运行
        await asyncio.gather(web_task, asyncio.sleep(float('inf')))
    except (KeyboardInterrupt, SystemExit):
        logger.info("AutoFilm 程序退出！")
        if telegram_bot:
            # 停止Telegram机器人
            await telegram_bot.stop()
        # 关闭调度器
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())