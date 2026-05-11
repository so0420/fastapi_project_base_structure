import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# 로그 디렉토리 설정
LOG_DIR = os.getenv("LOG_FILE_PATH", "app/logs/")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

# Windows 콘솔 한글 깨짐 방지 (표준 출력을 UTF-8로 설정)
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')


class ColoredFormatter(logging.Formatter):
    """콘솔 출력을 위한 색상 포맷터"""

    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"
    bold_red = "\033[1;31m"
    cyan = "\033[96m"
    reset = "\033[0m"

    FORMAT = '[%(asctime)s] %(levelname)-8s [%(name)s | %(filename)s:%(lineno)d] - %(message)s'

    LEVEL_COLORS = {
        logging.DEBUG: cyan,
        logging.INFO: green,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: bold_red,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.reset)
        original_levelname = record.levelname
        record.levelname = f"{color}{original_levelname:8s}{self.reset}"
        formatter = logging.Formatter(self.FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
        result = formatter.format(record)
        record.levelname = original_levelname
        return result


def get_logger(name: str = "songbook"):
    """
    설정된 로거를 반환합니다.
    콘솔에는 INFO 레벨 이상, 파일에는 DEBUG 레벨 이상을 기록합니다.
    """
    logger = logging.getLogger(name)

    # 이미 핸들러가 설정되어 있다면 중복 추가 방지
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 파일용 포맷터
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(name)s | %(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 콘솔 핸들러 (색상 포맷터)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 파일 핸들러 (자정마다 로테이션)
    current_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    log_file = os.path.join(LOG_DIR, f"{current_time}.log")

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger


def setup_uvicorn_logging():
    """
    uvicorn, fastapi 로거를 앱 로거의 핸들러(파일+콘솔)와 통합합니다.
    이 함수를 호출하지 않으면 uvicorn/fastapi 로그는 파일에 기록되지 않습니다.
    """
    target_loggers = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "fastapi",
    ]

    uvicorn_format = '[%(asctime)s] %(levelname)-8s [uvicorn] - %(message)s'

    uvicorn_console_formatter = ColoredFormatter()
    uvicorn_console_formatter.FORMAT = uvicorn_format

    uvicorn_file_formatter = logging.Formatter(uvicorn_format, datefmt='%Y-%m-%d %H:%M:%S')

    # 앱 로거의 파일 핸들러 경로를 가져옴
    app_logger = get_logger()
    log_file = None
    for h in app_logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            log_file = h.baseFilename
            break

    for logger_name in target_loggers:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []

        console_h = logging.StreamHandler(sys.stdout)
        console_h.setLevel(logging.INFO)
        console_h.setFormatter(uvicorn_console_formatter)
        uvicorn_logger.addHandler(console_h)

        if log_file:
            file_h = TimedRotatingFileHandler(
                log_file,
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8"
            )
            file_h.setLevel(logging.DEBUG)
            file_h.setFormatter(uvicorn_file_formatter)
            uvicorn_logger.addHandler(file_h)

        uvicorn_logger.propagate = False
        uvicorn_logger.setLevel(logging.INFO)


# 기본 로거 인스턴스
logger = get_logger()


def handle_exception(exc_type, exc_value, exc_traceback):
    """
    처리되지 않은 동기 예외를 캐치하여 로거에 기록합니다.
    (KeyboardInterrupt는 제외하여 정상 종료를 방해하지 않음)
    비동기(FastAPI 라우트) 예외는 global_exception_handler에서 처리합니다.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("Unhandled exception occurred!", exc_info=(exc_type, exc_value, exc_traceback))


# 전역 예외 처리기 등록 (동기 코드용)
sys.excepthook = handle_exception
