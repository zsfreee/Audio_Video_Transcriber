import os
import re
import requests
import tempfile
from urllib.parse import urlparse, parse_qs
import gdown
from typing import Optional, Dict, List, Tuple
import logging
from pathlib import Path

# Настройка логирования
logging.basicConfig(level=logging.WARNING,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('gdrive_service')

class GoogleDriveDownloader:
    """
    Класс для загрузки аудио и видео файлов из Google Drive
    с поддержкой скачивания отдельных файлов и папок
    """

    def __init__(self, output_dir: str = "./downloads"):
        """
        Инициализирует загрузчик Google Drive

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

    def is_gdrive_url(self, url: str) -> bool:
        """
        Проверяет, является ли URL ссылкой на Google Drive

        Args:
            url: URL для проверки

        Returns:
            True, если URL указывает на Google Drive
        """
        gdrive_patterns = [
            r'https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
            r'https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
            r'https?://docs\.google\.com/document/d/([a-zA-Z0-9_-]+)',
            r'https?://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)'
        ]

        for pattern in gdrive_patterns:
            if re.match(pattern, url):
                return True

        return False

    def extract_file_id(self, url: str) -> Optional[str]:
        """
        Извлекает ID файла или папки из URL Google Drive

        Args:
            url: URL Google Drive

        Returns:
            ID файла или папки, или None, если URL не распознан
        """
        # Проверяем URL с файлом
        file_match = re.search(r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', url)
        if file_match:
            return file_match.group(1)

        # Проверяем URL с открытием по ID
        open_match = re.search(r'open\?id=([a-zA-Z0-9_-]+)', url)
        if open_match:
            return open_match.group(1)

        # Проверяем URL с папкой
        folder_match = re.search(r'drive/folders/([a-zA-Z0-9_-]+)', url)
        if folder_match:
            return folder_match.group(1)

        # Проверяем URL с Google Doc
        doc_match = re.search(r'document/d/([a-zA-Z0-9_-]+)', url)
        if doc_match:
            return doc_match.group(1)

        # Если прямая ссылка с ID в параметре
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        if 'id' in query_params:
            return query_params['id'][0]

        return None

    def is_folder_url(self, url: str) -> bool:
        """
        Проверяет, является ли URL ссылкой на папку Google Drive

        Args:
            url: URL для проверки

        Returns:
            True, если URL указывает на папку
        """
        return bool(re.search(r'drive/folders/([a-zA-Z0-9_-]+)', url))

    def list_folder_contents(self, folder_id: str) -> List[Dict]:
        """
        Получает список файлов в папке Google Drive

        Args:
            folder_id: ID папки

        Returns:
            Список словарей с информацией о файлах
        """
        try:
            url = f"https://drive.google.com/drive/folders/{folder_id}"
            output_dir = os.path.join(self.output_dir, f"temp_folder_{folder_id}")

            # Создаем временную директорию для скачивания файлов
            os.makedirs(output_dir, exist_ok=True)

            # Используем gdown.download_folder вместо list_folder_files
            downloaded_files = []
            try:
                logger.info(f"Начинаем скачивание папки: {url}")

                # Скачиваем папку целиком
                gdown.download_folder(
                    url=url,
                    output=output_dir,
                    quiet=False,
                    use_cookies=False
                )

                # Собираем информацию о скачанных файлах
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        file_rel_path = os.path.relpath(file_path, output_dir)

                        # Фильтруем только аудио и видео файлы
                        file_ext = Path(file).suffix.lower()
                        if file_ext in ['.mp3', '.mp4', '.wav', '.m4a', '.avi', '.mov']:
                            downloaded_files.append({
                                'id': f"local_{len(downloaded_files)}",
                                'name': file_rel_path,
                                'path': file_path
                            })

                logger.info(f"Скачано {len(downloaded_files)} файлов из папки")
                return downloaded_files

            except Exception as e:
                logger.error(f"Ошибка при скачивании папки: {e}")
                return []

        except Exception as e:
            logger.error(f"Ошибка при получении содержимого папки: {e}")
            return []

    def download_file(self, file_id: str, output_filename: Optional[str] = None,
                     progress_callback=None) -> Optional[str]:
        """
        Скачивает файл с Google Drive

        Args:
            file_id: ID файла Google Drive
            output_filename: Имя выходного файла (без расширения)
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            Путь к загруженному файлу или None в случае ошибки
        """
        try:
            # Создаем URL для файла
            file_url = f"https://drive.google.com/uc?id={file_id}"

            if progress_callback:
                progress_callback(10, "Начинаем загрузку файла с Google Drive...")

            # Сначала получаем информацию о файле, чтобы узнать его реальное имя
            if not output_filename:
                try:
                    # Получаем информацию о файле через HEAD запрос к странице просмотра
                    view_url = f"https://drive.google.com/file/d/{file_id}/view"
                    response = requests.get(view_url)

                    # Ищем заголовок страницы, который обычно содержит имя файла
                    title_match = re.search(r'<title>([^<]+)( - Google Drive)?</title>', response.text)

                    if title_match:
                        # Извлекаем имя файла из заголовка
                        filename = title_match.group(1).strip()
                        # Очищаем имя файла от недопустимых символов
                        output_filename = self.sanitize_filename(filename)
                        logger.info(f"Получено реальное имя файла: {output_filename}")
                    else:
                        # Если не удалось получить имя, используем временное имя с ID
                        output_filename = f"gdrive_{file_id}"
                        logger.warning(f"Не удалось получить реальное имя файла, используем: {output_filename}")
                except Exception as e:
                    # В случае ошибки используем временное имя файла
                    output_filename = f"gdrive_{file_id}"
                    logger.warning(f"Ошибка при получении имени файла: {str(e)}, используем: {output_filename}")

            # Определяем путь для сохранения
            output_path = os.path.join(self.output_dir, output_filename)

            if progress_callback:
                progress_callback(30, f"Скачиваем файл: {output_filename}...")

            # Скачиваем файл с использованием gdown и реального имени файла
            try:
                downloaded_path = gdown.download(file_url, output_path, quiet=False)
            except Exception as e:
                # Если gdown не смог скачать файл по какой-то причине, пробуем другой подход
                logger.warning(f"Ошибка при скачивании с gdown: {str(e)}")
                try:
                    # Попытка 2: напрямую через requests
                    logger.info("Пробуем скачать файл через requests")
                    # URL для скачивания файла
                    download_url = f"https://drive.google.com/uc?id={file_id}&export=download"
                    # Запрос на скачивание
                    response = requests.get(download_url, stream=True)
                    response.raise_for_status()

                    # Сохраняем файл
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    downloaded_path = output_path
                    logger.info(f"Файл успешно скачан через requests: {downloaded_path}")
                except Exception as inner_e:
                    logger.error(f"Ошибка при скачивании через requests: {str(inner_e)}")
                    return None

            if progress_callback:
                progress_callback(100, "Загрузка завершена")

            if downloaded_path:
                logger.info(f"Файл успешно загружен: {downloaded_path}")
                return downloaded_path
            else:
                logger.error("Не удалось загрузить файл")
                return None

        except Exception as e:
            logger.error(f"Ошибка при загрузке файла: {str(e)}")
            if progress_callback:
                progress_callback(0, f"Ошибка загрузки: {str(e)}")
            return None

    def download_folder(self, folder_id: str, progress_callback=None) -> List[str]:
        """
        Скачивает все файлы из папки Google Drive

        Args:
            folder_id: ID папки Google Drive
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            Список путей к загруженным файлам
        """
        try:
            if progress_callback:
                progress_callback(10, "Начинаем загрузку папки с Google Drive...")

            # Создаем URL папки
            url = f"https://drive.google.com/drive/folders/{folder_id}"
            output_dir = os.path.join(self.output_dir, f"temp_folder_{folder_id}")

            # Создаем временную директорию для скачивания файлов
            os.makedirs(output_dir, exist_ok=True)

            if progress_callback:
                progress_callback(20, "Скачиваем содержимое папки...")

            # Скачиваем папку целиком
            try:
                gdown.download_folder(
                    url=url,
                    output=output_dir,
                    quiet=False,
                    use_cookies=False
                )
            except Exception as e:
                logger.error(f"Ошибка при скачивании папки: {str(e)}")
                if progress_callback:
                    progress_callback(0, f"Ошибка загрузки папки: {str(e)}")
                return []

            if progress_callback:
                progress_callback(80, "Сканируем загруженные файлы...")

            # Собираем информацию о скачанных файлах
            downloaded_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    file_path = os.path.join(root, file)

                    # Фильтруем только аудио и видео файлы
                    file_ext = Path(file).suffix.lower()
                    if file_ext in ['.mp3', '.mp4', '.wav', '.m4a', '.avi', '.mov']:
                        downloaded_files.append(file_path)

            if progress_callback:
                progress_callback(100, f"Загружено {len(downloaded_files)} файлов")

            logger.info(f"Скачано {len(downloaded_files)} аудио/видео файлов из папки")
            return downloaded_files

        except Exception as e:
            logger.error(f"Ошибка при загрузке папки: {str(e)}")
            if progress_callback:
                progress_callback(0, f"Ошибка загрузки папки: {str(e)}")
            return []

    def process_gdrive_url(self, url: str, progress_callback=None) -> List[str]:
        """
        Обрабатывает URL Google Drive и загружает файлы

        Args:
            url: URL Google Drive (файл или папка)
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            Список путей к загруженным файлам
        """
        # Проверяем, что это URL Google Drive
        if not self.is_gdrive_url(url):
            if progress_callback:
                progress_callback(0, "Указанный URL не является ссылкой на Google Drive")
            logger.error("Указанный URL не является ссылкой на Google Drive")
            return []

        # Извлекаем ID файла или папки
        file_or_folder_id = self.extract_file_id(url)
        if not file_or_folder_id:
            if progress_callback:
                progress_callback(0, "Не удалось извлечь ID файла или папки из URL")
            logger.error("Не удалось извлечь ID файла или папки из URL")
            return []

        # Если это ссылка на папку
        if self.is_folder_url(url):
            if progress_callback:
                progress_callback(10, "Обнаружена папка Google Drive, загружаем файлы...")
            return self.download_folder(folder_id=file_or_folder_id, progress_callback=progress_callback)

        # Если это ссылка на файл
        else:
            if progress_callback:
                progress_callback(10, "Обнаружен файл Google Drive, загружаем...")
            downloaded_file = self.download_file(
                file_id=file_or_folder_id,
                progress_callback=progress_callback
            )
            return [downloaded_file] if downloaded_file else []
