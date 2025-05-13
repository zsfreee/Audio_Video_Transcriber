import os
import re
import instaloader
import tempfile
from pathlib import Path
import logging
import subprocess
import requests
import json
import time
import shutil  # Добавляем модуль shutil для копирования файлов

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class InstagramDownloader:
    """Класс для загрузки медиа файлов из Instagram"""

    def __init__(self, output_dir=None):
        """
        Инициализация загрузчика Instagram

        Args:
            output_dir: Директория для сохранения загруженных файлов
        """
        self.output_dir = output_dir or os.path.join(os.getcwd(), "downloads")
        os.makedirs(self.output_dir, exist_ok=True)

        # Инициализация instaloader
        self.loader = instaloader.Instaloader(
            dirname_pattern=self.output_dir,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False
        )

    def is_instagram_url(self, url):
        """
        Проверяет, является ли URL ссылкой на Instagram

        Args:
            url: URL для проверки

        Returns:
            bool: True, если URL является ссылкой на Instagram
        """
        instagram_patterns = [
            r'https?://(?:www\.)?instagram\.com/p/([^/?#&]+)',  # Посты
            r'https?://(?:www\.)?instagram\.com/reel/([^/?#&]+)', # Рилсы
            r'https?://(?:www\.)?instagram\.com/stories/([^/?#&]+)/(\d+)', # Сторис
        ]

        for pattern in instagram_patterns:
            if re.match(pattern, url):
                return True

        return False

    def extract_shortcode(self, url):
        """
        Извлекает идентификатор поста или рилса из URL

        Args:
            url: URL Instagram поста или рилса

        Returns:
            str: Идентификатор (shortcode) поста или рилса
        """
        # Для постов и рилсов
        match = re.search(r'/(p|reel)/([^/?#&]+)', url)
        if match:
            return match.group(2)

        # Для сторис (более сложный случай)
        match = re.search(r'/stories/([^/?#&]+)/(\d+)', url)
        if match:
            return f"stories_{match.group(1)}_{match.group(2)}"

        return None

    def _download_using_yt_dlp(self, url, output_path, progress_callback=None):
        """
        Загружает видео из Instagram с использованием yt-dlp

        Args:
            url: URL на Instagram пост или рилс
            output_path: Путь для сохранения файла
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            bool: True при успешной загрузке, иначе False
        """
        try:
            if progress_callback:
                progress_callback(30, "Загрузка видео с помощью yt-dlp...")

            # Импортируем yt-dlp (уже должен быть установлен в проекте для YouTube)
            import yt_dlp

            # Опции yt-dlp
            ydl_opts = {
                'format': 'best',
                'outtmpl': output_path,
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
            }

            # Загружаем видео
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Проверяем, что файл был загружен
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                if progress_callback:
                    progress_callback(70, "Видео успешно загружено с помощью yt-dlp")
                logger.info(f"Видео успешно загружено с помощью yt-dlp: {output_path}")
                return True
            else:
                logger.error("Не удалось загрузить видео с помощью yt-dlp")
                return False

        except Exception as e:
            logger.error(f"Ошибка при загрузке видео с помощью yt-dlp: {e}")
            return False

    def download_media(self, url, output_filename=None, progress_callback=None):
        """
        Загружает медиа файл из Instagram

        Args:
            url: URL на Instagram пост, рилс или сторис
            output_filename: Имя выходного файла (без расширения)
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            str: Путь к загруженному медиа файлу или None в случае ошибки
        """
        if not self.is_instagram_url(url):
            logger.error(f"URL не распознан как ссылка на Instagram: {url}")
            return None

        shortcode = self.extract_shortcode(url)
        if not shortcode:
            logger.error(f"Не удалось извлечь shortcode из URL: {url}")
            return None

        # Формируем имя файла, если не указано
        if not output_filename:
            output_filename = f"instagram_{shortcode}"

        # Полный путь к выходному файлу
        output_path = os.path.join(self.output_dir, f"{output_filename}.mp4")

        # Пробуем разные методы загрузки
        try:
            if progress_callback:
                progress_callback(10, "Загрузка видео из Instagram...")

            # Сначала пробуем загрузить с помощью yt-dlp (обычно более надежный метод)
            if self._download_using_yt_dlp(url, output_path, progress_callback):
                if progress_callback:
                    progress_callback(100, "Видео успешно загружено")
                return output_path

            logger.info("Не удалось загрузить с помощью yt-dlp, пробуем с помощью instaloader...")

            # Если не удалось загрузить с помощью yt-dlp, пробуем через instaloader
            if '/p/' in url or '/reel/' in url:
                if progress_callback:
                    progress_callback(40, "Попытка загрузки через instaloader...")

                try:
                    # Загрузка поста или рилса через instaloader
                    post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

                    # Проверяем, есть ли видео
                    if not post.is_video:
                        logger.error("Данный пост не содержит видео")
                        return None

                    # Временная директория для загрузки
                    with tempfile.TemporaryDirectory() as temp_dir:
                        # Настройка временной директории для загрузки
                        temp_loader = instaloader.Instaloader(
                            dirname_pattern=temp_dir,
                            download_video_thumbnails=False,
                            download_geotags=False,
                            download_comments=False,
                            save_metadata=False,
                            compress_json=False
                        )

                        # Загрузка поста
                        temp_loader.download_post(post, target=shortcode)

                        if progress_callback:
                            progress_callback(80, "Перемещение видео в целевую директорию...")

                        # Находим видео файл в временной директории
                        video_found = False
                        for file in Path(temp_dir).glob(f"**/*{shortcode}*.mp4"):
                            # Копируем файл в целевую директорию
                            try:
                                shutil.copy2(str(file), output_path)
                                video_found = True
                                logger.info(f"Видео успешно загружено: {output_path}")
                                break
                            except Exception as e:
                                logger.error(f"Ошибка при копировании файла: {e}")

                        if video_found:
                            if progress_callback:
                                progress_callback(100, "Загрузка завершена")
                            return output_path

                except Exception as e:
                    logger.error(f"Ошибка при загрузке через instaloader: {e}")

            elif '/stories/' in url:
                # Для сторис нужна аутентификация
                logger.error("Загрузка сторис требует аутентификации в Instagram")
                if progress_callback:
                    progress_callback(100, "Ошибка: загрузка сторис требует аутентификации")
                return None

            # Если все методы не сработали, сообщаем об ошибке
            logger.error("Не удалось загрузить видео ни одним из доступных методов")
            if progress_callback:
                progress_callback(100, "Ошибка: не удалось загрузить видео")
            return None

        except Exception as e:
            logger.error(f"Неизвестная ошибка при загрузке из Instagram: {e}")
            if progress_callback:
                progress_callback(100, f"Ошибка: {str(e)}")
            return None

        return None

    def download_audio(self, url, output_filename=None, progress_callback=None):
        """
        Загружает видео файл из Instagram и извлекает из него аудио

        Args:
            url: URL на Instagram пост, рилс или сторис
            output_filename: Имя выходного файла (без расширения)
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            str: Путь к извлеченному аудио файлу или None в случае ошибки
        """
        try:
            # Получаем shortcode из URL для формирования имени файла
            shortcode = self.extract_shortcode(url)
            if not shortcode:
                logger.error(f"Не удалось извлечь shortcode из URL: {url}")
                return None

            # Формируем имя файла если не указано
            if not output_filename:
                output_filename = f"instagram_{shortcode}"

            # Сначала загружаем видео
            if progress_callback:
                progress_callback(10, "Загрузка видео из Instagram...")

            video_path = self.download_media(url, output_filename, progress_callback)

            if not video_path:
                logger.error("Не удалось загрузить видео из Instagram")
                return None

            # Путь к выходному аудио файлу
            audio_path = os.path.join(self.output_dir, f"{output_filename}.mp3")

            if progress_callback:
                progress_callback(60, "Извлечение аудио дорожки...")

            # Определение пути к ffmpeg
            ffmpeg_path = "ffmpeg"  # По умолчанию используем системный ffmpeg

            # Если мы на Windows, и ffmpeg.exe есть в текущей директории, используем его
            if os.name == 'nt' and os.path.exists(os.path.join(os.getcwd(), "ffmpeg.exe")):
                ffmpeg_path = os.path.join(os.getcwd(), "ffmpeg.exe")

            # Извлекаем аудио дорожку с помощью ffmpeg
            ffmpeg_command = [
                ffmpeg_path,
                "-i", video_path,  # Входной файл
                "-q:a", "0",       # Качество аудио (0 = наилучшее)
                "-map", "a",       # Только аудио
                "-y",              # Перезаписать выходной файл если существует
                audio_path         # Выходной файл
            ]

            # Выполняем команду ffmpeg
            process = subprocess.Popen(
                ffmpeg_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            _, stderr = process.communicate()

            # Если ffmpeg завершился с ошибкой
            if process.returncode != 0:
                logger.error(f"Ошибка при извлечении аудио: {stderr.decode()}")
                if progress_callback:
                    progress_callback(100, "Ошибка при извлечении аудио")
                return None

            # Проверяем, создался ли файл аудио
            if not os.path.exists(audio_path):
                logger.error("Аудио файл не был создан")
                if progress_callback:
                    progress_callback(100, "Ошибка: аудио файл не был создан")
                return None

            if progress_callback:
                progress_callback(100, "Аудио успешно извлечено")

            logger.info(f"Аудио успешно извлечено: {audio_path}")
            return audio_path

        except Exception as e:
            logger.error(f"Ошибка при извлечении аудио из Instagram видео: {e}")
            if progress_callback:
                progress_callback(100, f"Ошибка: {str(e)}")
            return None

# Пример использования
if __name__ == "__main__":
    downloader = InstagramDownloader()
    url = "https://www.instagram.com/reel/DDrvwBqoMhn/"
    audio_path = downloader.download_audio(url)
    print(f"Извлеченное аудио: {audio_path}")
