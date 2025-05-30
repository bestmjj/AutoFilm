from typing import Final

# VIDEO_EXTS: Final = frozenset(
#     (".mp4", ".mkv", ".flv", ".avi", ".wmv", ".ts", ".rmvb", ".webm", "wmv", ".mpg")
# )  # 视频文件后缀
# EXTENDED_VIDEO_EXTS: Final = VIDEO_EXTS.union((".strm",))  # 扩展视频文件后缀

# SUBTITLE_EXTS: Final = frozenset((".ass", ".srt", ".ssa", ".sub"))  # 字幕文件后缀

# IMAGE_EXTS: Final = frozenset((".png", ".jpg"))

# NFO_EXTS: Final = frozenset((".nfo",))



# 视频和音频文件后缀
VIDEO_EXTS: Final = frozenset(
    (
        ".mp4",  # MPEG-4 视频
        ".mkv",  # Matroska 视频
        ".flv",  # Flash 视频
        ".avi",  # Audio Video Interleave
        ".wmv",  # Windows Media Video
        ".ts",   # MPEG Transport Stream
        ".rmvb", # RealMedia Variable Bitrate
        ".webm", # WebM 视频
        ".mpg",  # MPEG-1/2 视频
        ".mpeg", # MPEG 视频
        ".mov",  # QuickTime 视频
        ".m2ts", # Blu-ray MPEG-2 Transport Stream
        ".vob",  # DVD Video Object
        ".3gp",  # 3GPP 移动设备视频
        ".ogv",  # Ogg 视频
        ".divx", # DivX 编码视频
        ".asf",  # Advanced Systems Format
        ".m4v",  # iTunes 视频格式
        ".mp3",  # MPEG Audio Layer III
        ".aac",  # Advanced Audio Coding
        ".flac", # Free Lossless Audio Codec
        ".wav",  # Waveform Audio File Format
        ".ogg",  # Ogg Vorbis 音频
        ".m4a",  # MPEG-4 Audio
        ".wma",  # Windows Media Audio
        ".ac3",  # Audio Codec 3
        ".opus", # Opus 音频
        ".alac", # Apple Lossless Audio Codec
        ".mka",  # Matroska Audio
    )
)

# 扩展视频文件后缀（包括 .strm）
EXTENDED_VIDEO_EXTS: Final = VIDEO_EXTS.union((".strm",))

# 字幕文件后缀
SUBTITLE_EXTS: Final = frozenset(
    (
        ".ass",  # Advanced SubStation Alpha
        ".srt",  # SubRip 字幕
        ".ssa",  # SubStation Alpha
        ".sub",  # 字幕文件
        ".vtt",  # WebVTT 字幕
        ".smi",  # SAMI 字幕
        ".idx",  # VobSub 字幕索引
    )
)

# 图片文件后缀
IMAGE_EXTS: Final = frozenset(
    (
        ".png",  # Portable Network Graphics
        ".jpg",  # JPEG 图片
        ".jpeg", # JPEG 图片
        ".gif",  # Graphics Interchange Format
        ".bmp",  # Bitmap 图片
        ".tiff", # Tagged Image File Format
        ".webp", # WebP 图片
    )
)

# NFO 文件后缀
NFO_EXTS: Final = frozenset((".nfo",))
