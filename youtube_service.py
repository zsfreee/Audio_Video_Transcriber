import os
import re
import yt_dlp
from typing import Optional, Dict, Any, List, Tuple
import logging

# Настройка логирования с более низким уровнем подробности
logging.basicConfig(level=logging.WARNING,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('youtube_service')

class YouTubeDownloader:
    """
    Класс для скачивания аудио из YouTube видео
    с улучшенной обработкой ошибок и диагностикой
    """

    def __init__(self, output_dir: str = "./downloads"):
        """
        Инициализирует загрузчик YouTube

        Args:
            output_dir: Директория для сохранения файлов
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def sanitize_filename(self, filename: str) -> str:
        """
        Очищает имя файла от недопустимых символов

        Args:
            filename: Исходное имя файла

        Returns:
            Безопасное имя файла
        """
        # Заменяем недопустимые для файловой системы символы
        return re.sub(r'[\\/*?:"<>|]', "_", filename)

    def get_video_info(self, url: str) -> Dict[str, Any]:
        """
        Получает информацию о видео

        Args:
            url: URL видео на YouTube

        Returns:
            Словарь с информацией о видео
        """
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.error(f"Ошибка при получении информации о видео: {e}")
            return {}

    def download_audio(self, url: str, output_filename: Optional[str] = None,
                      progress_callback=None) -> Optional[str]:
        """
        Скачивает аудио из YouTube видео

        Args:
            url: URL видео на YouTube
            output_filename: Имя выходного файла (без расширения)
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            Путь к загруженному аудио файлу или None в случае ошибки
        """
        # Получаем информацию о видео
        info = self.get_video_info(url)
        if not info:
            logger.error("Не удалось получить информацию о видео")
            return None

        # Если имя файла не указано, используем название видео
        if not output_filename:
            output_filename = self.sanitize_filename(info.get('title', 'youtube_audio'))

        # Формируем полный путь к файлу (без расширения)
        output_path = os.path.join(self.output_dir, output_filename)

        # Настройки для загрузки
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'noplaylist': True,  # Только видео, не плейлист
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'verbose': False
        }

        # Если передана функция обратного вызова для прогресса
        if progress_callback:
            def ydl_progress_hook(d):
                if d['status'] == 'downloading':
                    total_bytes = d.get('total_bytes', 0)
                    if total_bytes > 0:
                        downloaded = d.get('downloaded_bytes', 0)
                        percent = (downloaded / total_bytes) * 100
                        progress_callback(percent, f"Загрузка: {percent:.1f}%")
                    else:
                        # Если общий размер неизвестен, используем другую метрику
                        percent_str = d.get('_percent_str', '0%').strip()
                        try:
                            percent = float(percent_str.replace('%', ''))
                            progress_callback(percent, f"Загрузка: {percent:.1f}%")
                        except:
                            pass
                elif d['status'] == 'finished':
                    progress_callback(100, "Загрузка завершена, обработка файла...")

            ydl_opts['progress_hooks'] = [ydl_progress_hook]

        # Выполняем загрузку
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Начинаем загрузку: {url}")
                ydl.download([url])

            # Проверяем, какой файл был создан
            result_file = f"{output_path}.mp3"

            if os.path.exists(result_file):
                logger.info(f"Файл успешно загружен: {result_file}")
                return result_file

            # Если файл не найден с ожидаемым расширением, ищем другие варианты
            for ext in ['.m4a', '.wav', '.opus', '.webm', '.mp3']:
                possible_file = f"{output_path}{ext}"
                if os.path.exists(possible_file):
                    logger.info(f"Найден файл с другим расширением: {possible_file}")
                    return possible_file

            return None

        except Exception as e:
            logger.error(f"Ошибка при загрузке аудио: {str(e)}")
            return None

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """
        Проверяет, является ли URL адресом YouTube видео

        Args:
            url: URL для проверки

        Returns:
            True, если URL указывает на YouTube видео
        """
        youtube_patterns = [
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
            r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)'
        ]

        for pattern in youtube_patterns:
            if re.match(pattern, url):
                return True

        return False

    def get_video_id(self, url: str) -> Optional[str]:
        """
        Извлекает ID видео из URL YouTube

        Args:
            url: URL YouTube видео

        Returns:
            ID видео или None, если URL не распознан
        """
        patterns = [
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
            r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None
