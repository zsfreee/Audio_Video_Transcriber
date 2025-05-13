import os
import requests
import re
from pathlib import Path
from urllib.parse import urlparse, unquote

# Список допустимых расширений для аудио и видео
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.mp4', '.mov', '.avi', '.mkv', '.webm'}

class YandexDiskDownloader:
    def __init__(self, output_dir):
        """
        Инициализация загрузчика Яндекс Диска

        Args:
            output_dir: Директория для сохранения скачанных файлов
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def is_yandex_disk_url(self, url):
        """
        Проверяет, является ли URL ссылкой на Яндекс Диск

        Args:
            url: URL для проверки

        Returns:
            bool: True, если это ссылка на Яндекс Диск, иначе False
        """
        return bool(url and "disk.yandex" in url)

    def is_allowed_file(self, filename):
        """
        Проверяет, является ли файл допустимым аудио или видео файлом

        Args:
            filename: Имя файла для проверки

        Returns:
            bool: True, если это аудио или видео файл, иначе False
        """
        return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

    def download_file(self, public_url, save_path, progress_callback=None):
        """
        Скачивает файл с публичной ссылки Яндекс Диска

        Args:
            public_url: Публичная ссылка на файл Яндекс Диска
            save_path: Путь для сохранения файла
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            str: Путь к сохраненному файлу или None в случае ошибки
        """
        try:
            # Сообщаем о начале загрузки
            if progress_callback:
                progress_callback(10, f"Получение прямой ссылки для {Path(save_path).name}...")

            # Получаем прямую ссылку на скачивание
            api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
            params = {'public_key': public_url}
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            download_url = response.json()['href']

            if progress_callback:
                progress_callback(30, f"Начало скачивания {Path(save_path).name}...")

            # Скачиваем файл с поддержкой потокового режима
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                total_length = int(r.headers.get('content-length', 0))

                # Создаем директории, если они не существуют
                os.makedirs(os.path.dirname(save_path), exist_ok=True)

                with open(save_path, 'wb') as f:
                    if total_length == 0:  # Неизвестный размер
                        f.write(r.content)
                    else:  # Известный размер
                        dl = 0
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                dl += len(chunk)
                                f.write(chunk)
                                if progress_callback:
                                    # Прогресс от 30% до 90%
                                    progress = 30 + int(min(60 * dl / total_length, 60))
                                    progress_callback(progress, f"Скачивание: {dl * 100 // total_length}%")

            if progress_callback:
                progress_callback(100, f"Файл {Path(save_path).name} успешно загружен")

            return save_path
        except Exception as e:
            if progress_callback:
                progress_callback(0, f"Ошибка: {str(e)}")
            print(f"Ошибка при скачивании файла: {str(e)}")
            return None

    def get_folder_items(self, public_url, progress_callback=None):
        """
        Получает список элементов из публичной папки Яндекс Диска

        Args:
            public_url: Публичная ссылка на папку Яндекс Диска
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            list: Список элементов в папке или None в случае ошибки
        """
        try:
            if progress_callback:
                progress_callback(10, "Получение списка файлов из папки...")

            api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
            params = {
                'public_key': public_url,
                'limit': 1000
            }
            response = requests.get(api_url, params=params)
            response.raise_for_status()

            if progress_callback:
                progress_callback(20, "Анализ содержимого папки...")

            return response.json()['_embedded']['items']
        except Exception as e:
            if progress_callback:
                progress_callback(0, f"Ошибка: {str(e)}")
            print(f"Ошибка при получении содержимого папки: {str(e)}")
            return None

    def download_folder_files(self, public_url, items, progress_callback=None):
        """
        Скачивает аудио и видео файлы из публичной папки Яндекс Диска

        Args:
            public_url: Публичная ссылка на папку Яндекс Диска
            items: Список элементов в папке
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            list: Список путей к сохраненным файлам
        """
        downloaded_files = []

        # Фильтруем только аудио и видео файлы
        media_files = [item for item in items if
                      item['type'] == 'file' and
                      self.is_allowed_file(item['name'])]

        if not media_files and progress_callback:
            progress_callback(0, "В папке не найдено аудио или видео файлов")
            return []

        total_files = len(media_files)

        for i, item in enumerate(media_files):
            file_name = item['name']
            file_path = os.path.join(self.output_dir, file_name)

            # Создаем прокси для индивидуального прогресса файла
            def file_progress_callback(percent, message):
                if progress_callback:
                    # Общий прогресс, учитывая процент выполненных файлов
                    overall_percent = int(20 + (80 * (i / total_files + (percent / 100) / total_files)))
                    progress_callback(overall_percent, f"[{i+1}/{total_files}] {message}")

            # ИСПРАВЛЕНО: Используем file_id из метаданных файла вместо конкатенации URL
            # Получаем прямую ссылку для скачивания данного файла, используя путь из API
            api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
            # Используем публичную ссылку файла из его свойств
            file_public_url = item.get('public_url') or item.get('file')

            # Если нет прямой ссылки на файл, используем path из метаданных
            if not file_public_url:
                download_params = {'public_key': public_url, 'path': item.get('path', '')}
            else:
                download_params = {'public_key': file_public_url}

            try:
                file_progress_callback(10, f"Получение ссылки для скачивания {file_name}...")
                download_response = requests.get(api_url, params=download_params)
                download_response.raise_for_status()
                download_url = download_response.json()['href']

                file_progress_callback(20, f"Начало скачивания {file_name}...")
                # Скачиваем файл с отображением прогресса
                with requests.get(download_url, stream=True) as r:
                    r.raise_for_status()
                    total_length = int(r.headers.get('content-length', 0))

                    with open(file_path, 'wb') as f:
                        if total_length == 0:
                            f.write(r.content)
                            file_progress_callback(100, f"Файл {file_name} загружен")
                        else:
                            dl = 0
                            for chunk in r.iter_content(chunk_size=8192):
                                if chunk:
                                    dl += len(chunk)
                                    f.write(chunk)
                                    percent = min(100, int(dl * 100 / total_length))
                                    file_progress_callback(percent, f"Скачивание {file_name}: {percent}%")

                downloaded_files.append(file_path)

            except Exception as e:
                file_progress_callback(0, f"Ошибка при загрузке {file_name}: {str(e)}")
                print(f"Ошибка при скачивании файла {file_name}: {str(e)}")

                # Запасной вариант, если не сработал основной метод
                try:
                    file_progress_callback(10, f"Пробуем альтернативный метод скачивания для {file_name}...")
                    # Пробуем создать ссылку вручную (для обратной совместимости)
                    alternative_params = {'public_key': public_url, 'path': f"/{file_name}"}
                    download_response = requests.get(api_url, params=alternative_params)
                    download_response.raise_for_status()
                    download_url = download_response.json()['href']

                    file_progress_callback(20, f"Начало скачивания {file_name} (альтернативный метод)...")
                    # Скачиваем файл с отображением прогресса
                    with requests.get(download_url, stream=True) as r:
                        r.raise_for_status()
                        total_length = int(r.headers.get('content-length', 0))

                        with open(file_path, 'wb') as f:
                            if total_length == 0:
                                f.write(r.content)
                                file_progress_callback(100, f"Файл {file_name} загружен")
                            else:
                                dl = 0
                                for chunk in r.iter_content(chunk_size=8192):
                                    if chunk:
                                        dl += len(chunk)
                                        f.write(chunk)
                                        percent = min(100, int(dl * 100 / total_length))
                                        file_progress_callback(percent, f"Скачивание {file_name}: {percent}%")

                    downloaded_files.append(file_path)
                except Exception as e2:
                    file_progress_callback(0, f"Ошибка при альтернативной загрузке {file_name}: {str(e2)}")
                    print(f"Ошибка при альтернативном скачивании файла {file_name}: {str(e2)}")
                    continue

        if progress_callback:
            progress_callback(100, f"Загружено файлов: {len(downloaded_files)}")

        return downloaded_files

    def extract_file_id(self, url):
        """
        Извлекает идентификатор файла из URL Яндекс Диска

        Args:
            url: URL Яндекс Диска

        Returns:
            str: Идентификатор файла или None, если не удалось извлечь
        """
        # Паттерн для файла (i/{id}) или папки (d/{id})
        patterns = [
            r'disk\.yandex\.[a-z]+/i/([a-zA-Z0-9_-]+)',
            r'disk\.yandex\.[a-z]+/d/([a-zA-Z0-9_-]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return None

    def is_folder_url(self, url):
        """
        Проверяет, является ли URL ссылкой на папку Яндекс Диска

        Args:
            url: URL для проверки

        Returns:
            bool: True, если это ссылка на папку, иначе False
        """
        return "/d/" in url

    def process_yandex_disk_url(self, url, progress_callback=None):
        """
        Обрабатывает URL Яндекс Диска, скачивая файл или все файлы из папки

        Args:
            url: URL на файл или папку Яндекс Диска
            progress_callback: Функция обратного вызова для отображения прогресса

        Returns:
            list: Список путей к сохраненным файлам или пустой список в случае ошибки
        """
        if not self.is_yandex_disk_url(url):
            if progress_callback:
                progress_callback(0, "Указанный URL не является ссылкой на Яндекс Диск")
            return []

        # Если это папка
        if self.is_folder_url(url):
            if progress_callback:
                progress_callback(5, "Обработка папки Яндекс Диска...")

            items = self.get_folder_items(url, progress_callback)
            if items:
                return self.download_folder_files(url, items, progress_callback)
            return []

        # Если это файл
        else:
            if progress_callback:
                progress_callback(5, "Обработка файла Яндекс Диска...")

            # Получаем имя файла из заголовков HTTP или используем ID
            file_id = self.extract_file_id(url) or "yandex_disk_file"

            # Пробуем получить реальное имя файла
            try:
                # Используем API для получения метаданных о файле и его реального имени
                api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
                params = {'public_key': url}
                response = requests.get(api_url, params=params)
                response.raise_for_status()

                file_name = response.json().get('name', file_id)
                if not self.is_allowed_file(file_name):
                    if progress_callback:
                        progress_callback(0, f"Файл {file_name} не является аудио или видео файлом")
                    return []
            except Exception:
                # Если не удалось получить имя, используем ID с расширением
                file_name = f"{file_id}.mp3"  # Добавляем расширение по умолчанию

            save_path = os.path.join(self.output_dir, file_name)
            result = self.download_file(url, save_path, progress_callback)

            return [result] if result else []
