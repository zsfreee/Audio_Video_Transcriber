import os
import streamlit as st
import shutil  # Добавляем импорт модуля shutil для копирования файлов
import sys  # Добавляем импорт sys для передачи пути к интерпретатору Python
import zipfile # Добавляем импорт для создания ZIP-архивов
from io import BytesIO # Добавляем импорт для буферов в памяти
import subprocess  # Добавляем импорт модуля subprocess для запуска внешних команд

# Конфигурация страницы Streamlit (должна быть первой командой Streamlit)
st.set_page_config(
    page_title="Транскрибатор",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Инициализируем переменные состояния сессии, если их еще нет
if 'last_processed_dir' not in st.session_state:
    st.session_state.last_processed_dir = None
if 'processed_dirs' not in st.session_state:
    st.session_state.processed_dirs = []
if 'process_completed' not in st.session_state:
    st.session_state.process_completed = False

import openai
import tempfile
import time
import re
import markdown
from pathlib import Path
from dotenv import load_dotenv
import utils
from utils import (
    transcribe_audio_whisper, audio_info,
    format_text, split_markdown_text, process_documents,
    num_tokens_from_string, split_text, process_text_chunks,
    save_text_to_docx, markdown_to_docx, setup_ffmpeg_path
)
from youtube_service import YouTubeDownloader
from gdrive_service import GoogleDriveDownloader
from instagram_service import InstagramDownloader
from yandex_disk_service import YandexDiskDownloader
from vk_video_service import VKVideoDownloader
import platform

# Загрузка переменных окружения из файла .env
load_dotenv()

# Получаем API ключ из Streamlit Secrets
if 'OPENAI_API_KEY' in st.secrets:
    openai.api_key = st.secrets['OPENAI_API_KEY']
else:
    st.error("OpenAI API ключ не найден в Streamlit Secrets. Пожалуйста, добавьте его в настройках Streamlit Cloud.")
    st.stop()

# Определяем пути для хранения файлов (используем /tmp для облака)
TEMP_DIR = os.path.join("/tmp", "transcriptor_temp")
TRANSCRIPTIONS_DIR = os.path.join(TEMP_DIR, "transcriptions")  # Для конечных файлов
TEMP_FILES_DIR = os.path.join(TEMP_DIR, "temp_files")  # Для временных файлов
AUDIO_FILES_DIR = os.path.join(TEMP_DIR, "audio_files")  # Для аудио файлов
MARKDOWN_DIR = os.path.join(TEMP_DIR, "markdown")  # Для хранения markdown файлов

# Создаем все необходимые директории
for dir_path in [TRANSCRIPTIONS_DIR, TEMP_FILES_DIR, AUDIO_FILES_DIR, MARKDOWN_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Устанавливаем переменные окружения для FFmpeg
setup_ffmpeg_path()

# Проверяем работоспособность FFmpeg
try:
    subprocess.run([os.environ["FFMPEG_BINARY"], "-version"], capture_output=True, text=True, check=True)
    st.sidebar.success("FFmpeg успешно инициализирован")
except Exception as e:
    st.sidebar.error(f"Ошибка при инициализации FFmpeg: {str(e)}")
    st.stop()

# Вспомогательная функция для получения более строгих языковых инструкций
def get_language_instruction(target_language):
    """
    Возвращает строгие языковые инструкции для указанного языка
    """
    if target_language.lower() == "казахский":
        return """БАРЛЫҚ МӘТІНДІ ТЕК ҚАЗАҚ ТІЛІНДЕ ЖАЗУ КЕРЕК.
        Басқа тілдерді қолданбаңыз.
        Тақырыптар, мәтін мазмұны, бөлімдер - бәрі қазақ тілінде болуы керек.
        Орыс немесе ағылшын сөздерін араластырмаңыз."""
    elif target_language.lower() == "английский":
        return """ALL TEXT MUST BE WRITTEN ONLY IN ENGLISH.
        Do not use other languages.
        Headings, content, sections - everything should be in English.
        Do not mix in Russian or Kazakh words."""
    else:  # русский по умолчанию
        return """ВЕСЬ ТЕКСТ ДОЛЖЕН БЫТЬ НАПИСАН ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
        Не используйте другие языки.
        Заголовки, содержание, разделы - всё должно быть на русском языке.
        Не смешивайте с казахскими или английскими словами."""

# Новая функция для создания кнопок скачивания файлов
def create_download_buttons(file_dir):
    """
    Создает кнопки для скачивания отдельных файлов и ZIP-архива всех файлов

    Args:
        file_dir: Директория, содержащая файлы для скачивания
    """
    # Добавляем текущую директорию в список обработанных, если она еще не там
    if file_dir not in st.session_state.processed_dirs and os.path.exists(file_dir):
        st.session_state.processed_dirs.append(file_dir)
        st.session_state.last_processed_dir = file_dir
        st.session_state.process_completed = True

    if not os.path.exists(file_dir):
        st.warning("Директория с файлами не найдена.")
        return

    # Получаем список всех файлов txt и docx в директории
    files = [f for f in os.listdir(file_dir) if f.endswith((".txt", ".docx"))]

    if not files:
        st.info("В этой директории пока нет файлов для скачивания.")
        return

    st.header("📄 Скачать результаты")

    # Создаем колонки для более компактного отображения кнопок
    cols = st.columns(2)

    # Создаем кнопки для скачивания отдельных файлов
    for i, file_name in enumerate(files):
        col_idx = i % 2  # Чередуем колонки
        file_path = os.path.join(file_dir, file_name)
        unique_key = f"download_{os.path.basename(file_dir)}_{file_name}_{i}_{abs(hash(file_dir))}"

        try:
            with open(file_path, "rb") as file:
                file_bytes = file.read()

            # Определяем MIME-тип в зависимости от расширения файла
            mime_type = "text/plain" if file_name.endswith(".txt") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            with cols[col_idx]:
                st.download_button(
                    label=f"📥 Скачать {file_name}",
                    data=file_bytes,
                    file_name=file_name,
                    mime=mime_type,
                    key=unique_key  # Уникальный ключ
                )
        except Exception as e:
            st.error(f"Ошибка при подготовке файла {file_name} для скачивания: {str(e)}")

    # Создаем ZIP-архив со всеми файлами
    st.subheader("📦 Скачать всё архивом")

    try:
        # Создаем буфер для архива в памяти
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for file_name in files:
                file_path = os.path.join(file_dir, file_name)
                zip_file.write(file_path, arcname=file_name)  # сохраняем без абсолютного пути

        zip_buffer.seek(0)  # перемещаем указатель в начало буфера

        zip_key = f"download_zip_{os.path.basename(file_dir)}_{len(files)}_{abs(hash(file_dir))}"
        st.download_button(
            label="📥 Скачать все файлы (ZIP)",
            data=zip_buffer,
            file_name=f"{os.path.basename(file_dir)}_results.zip",
            mime="application/zip",
            key=zip_key  # Уникальный ключ
        )
    except Exception as e:
        st.error(f"Ошибка при создании ZIP-архива: {str(e)}")

# Функция для создания конспекта из текста транскрибации с уникальными именами файлов
def create_handbook(text, save_path, original_filename, target_language="русский", save_txt=True, save_docx=True):
    st.write("### Создаем конспект из транскрибации...")

    # Получаем базовое имя файла без префикса, если он есть
    if original_filename.startswith("Conspect_"):
        original_filename = original_filename[len("Conspect_"):]

    # Определяем пути к файлам
    md_text_path = os.path.join(TEMP_FILES_DIR, f"{original_filename}_processed_md_text.txt")
    handbook_path = os.path.join(TEMP_FILES_DIR, f"{original_filename}_summary_draft.txt")

    # Пути к конечным файлам конспекта в папке экспорта
    handbook_export_txt_path = os.path.join(save_path, f"Summary_{original_filename}.txt")
    handbook_export_docx_path = os.path.join(save_path, f"Summary_{original_filename}.docx")

    # Определяем размер текста в токенах
    tokens = num_tokens_from_string(text)
    st.write(f"Количество токенов в тексте: {tokens}")

    # Получаем языковые инструкции для более строгого указания языка
    lang_instruction = get_language_instruction(target_language)

    # Системный промпт для разделения текста на разделы
    system_prompt = f"""Вы гений текста, копирайтинга, писательства. Ваша задача распознать разделы в тексте
и разбить его на эти разделы сохраняя весь текст на 100%. {lang_instruction}"""

    # Пользовательский промпт для разделения текста
    user_prompt = f"""Пожалуйста, давайте подумаем шаг за шагом: Подумайте, какие разделы в тексте вы можете
распознать и какое название по смыслу можно дать каждому разделу. Далее напишите ответ по всему
предыдущему ответу и оформи в порядке:
## Название раздела, после чего весь текст, относящийся к этому разделу. {lang_instruction} Текст:"""

    # В зависимости от размера текста либо обрабатываем текст целиком, либо делим на чанки
    md_processed_text = ""

    with st.spinner("Обрабатываем текст, разбивая на разделы..."):
        # Если текст небольшой (менее 16к токенов для безопасности), обрабатываем целиком
        if tokens < 16000:
            md_processed_text = utils.generate_answer(system_prompt, user_prompt, text)
        # Иначе разбиваем на чанки и обрабатываем по частям
        else:
            st.write("Текст слишком большой, разбиваем на части...")
            # Разбиваем текст на чанки
            text_chunks = split_text(text, chunk_size=30000, chunk_overlap=1000)
            st.write(f"Текст разбит на {len(text_chunks)} частей")
            # Обрабатываем каждый чанк отдельно
            md_processed_text = process_text_chunks(text_chunks, system_prompt, user_prompt)

    # Сохраняем промежуточный текст с разделами в txt файл в папке для временных файлов
    with open(md_text_path, "w", encoding="utf-8") as f:
        f.write(md_processed_text)

    # Копируем файл с разделами в папку markdown для длительного хранения
    markdown_file_path = os.path.join(MARKDOWN_DIR, f"{original_filename}_processed_md_text.txt")
    shutil.copy2(md_text_path, markdown_file_path)
    st.success(f"Текст с разделами сохранен и скопирован в папку markdown для длительного хранения")

    # Получаем список документов, разбитых по заголовкам
    chunks_md_splits = split_markdown_text(md_processed_text)
    st.write("### Заголовки разделов:")
    for chunk in chunks_md_splits:
        try:
            if "Header 2" in chunk.metadata:
                st.write(f"- {chunk.metadata['Header 2']}")
        except:
            pass

    # Системный промпт для формирования конспекта
    system_prompt_handbook = f"""Ты гений копирайтинга. Ты получаешь раздел необработанного текста по определенной теме.
Нужно из этого текста выделить самую суть, только самое важное, сохранив все нужные подробности и детали,
но убрав всю "воду" и слова (предложения), не несущие смысловой нагрузки.
ОЧЕНЬ ВАЖНО: {lang_instruction}
Ты ДОЛЖЕН писать ВЕСЬ текст ТОЛЬКО на {target_language} языке. НЕ ИСПОЛЬЗУЙ другие языки вообще."""

    # Пользовательский промпт для формирования конспекта
    user_prompt_handbook = f"""Из данного текста выдели только ключевую и ценную с точки зрения темы раздела информацию.
Удали всю "воду". В итоге у тебя должен получится раздел для конспекта по указанной теме. Опирайся
только на данный тебе текст, не придумывай ничего от себя. Ответ нужен в формате:
## Название раздела, и далее выделенная тобой ценная информация из текста. Используй маркдаун-разметку для выделения важных моментов:
**жирный текст** для важных фактов, *курсив* для определений, списки для перечислений и т.д.

ОЧЕНЬ ВАЖНО: {lang_instruction}
Ты ДОЛЖЕН писать ВЕСЬ текст ТОЛЬКО на {target_language} языке.
НЕ ИСПОЛЬЗУЙ русский или любой другой язык, кроме {target_language}.

Весь твой ответ должен быть на {target_language} языке, включая все заголовки, выделения и пояснения."""

    with st.spinner("Формируем конспект из разделов..."):
        # Обработка каждого документа (раздела) для формирования конспекта
        handbook_md_text = process_documents(
            TEMP_FILES_DIR,
            chunks_md_splits,
            system_prompt_handbook,
            user_prompt_handbook,
            original_filename,
            target_language
        )

    # Сохраняем черновик конспекта в файл для временных данных
    with open(handbook_path, "w", encoding="utf-8") as f:
        f.write(handbook_md_text)

    # Сохраняем конспект в указанную директорию экспорта в зависимости от выбранных опций
    if save_txt:
        with open(handbook_export_txt_path, "w", encoding="utf-8") as f:
            f.write(handbook_md_text)
        st.success(f"Конспект успешно создан и сохранен в TXT: {handbook_export_txt_path}")

    # Сохраняем конспект в docx с правильным форматированием, если выбрана опция
    if save_docx:
        markdown_to_docx(handbook_md_text, handbook_export_docx_path)
        st.success(f"Конспект успешно создан и сохранен в DOCX: {handbook_export_docx_path}")

    # Создаем текстовую область с конспектом для просмотра и копирования
    with st.expander("Просмотр конспекта", expanded=False):
        handbook_html = markdown.markdown(handbook_md_text)
        st.markdown(handbook_html, unsafe_allow_html=True)
        st.info("Для копирования выделите текст выше и нажмите Ctrl+C")

    # Добавляем возможность скачивания файлов конспекта
    create_download_buttons(save_path)

    return handbook_md_text, md_processed_text

# Функция для обработки загруженных локальных файлов
def process_uploaded_file(uploaded_file, save_dir, file_name, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    # Инициализируем переменную transcription как None
    transcription = None

    # Создаем временный файл для загруженного контента
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    # Создаем директорию для сохранения файлов текущего проекта
    file_dir = os.path.join(save_dir, file_name)
    os.makedirs(file_dir, exist_ok=True)

    try:
        # Получаем информацию об аудио
        audio_data = audio_info(tmp_file_path)
        st.write(f"Длительность: {audio_data.duration_seconds / 60:.2f} мин.")
        st.write(f"Частота дискретизации: {audio_data.frame_rate} Гц")
        st.write(f"Количество каналов: {audio_data.channels}")

        # Транскрибация аудио с помощью Whisper API
        with st.spinner("Транскрибация аудио..."):
            transcription, original_language = transcribe_audio_whisper(
                audio_path=tmp_file_path,
                file_title=file_name,
                save_folder_path=TEMP_FILES_DIR
            )

            if transcription:
                formatted_text = format_text(transcription)

                # Определяем путь для сохранения оригинальной транскрибации
                original_output_txt = os.path.join(file_dir, f"Original_{file_name}.txt")
                original_output_docx = os.path.join(file_dir, f"Original_{file_name}.docx")

                # Сохраняем оригинальную транскрибацию
                if save_txt:
                    with open(original_output_txt, "w", encoding="utf-8") as f:
                        f.write(formatted_text)
                    st.success(f"Оригинальная транскрибация сохранена в TXT: {original_output_txt}")

                if save_docx:
                    save_text_to_docx(formatted_text, original_output_docx)
                    st.success(f"Оригинальная транскрибация сохранена в DOCX: {original_output_docx}")

                st.success("Оригинальная транскрибация завершена!")
                with st.expander("Просмотреть оригинальный текст", expanded=False):
                    st.write(formatted_text)

                # Переводим транскрибацию на заданный язык, если транскрибация не на этом языке
                if target_language:
                    # Получаем языковые инструкции для более строгого указания языка
                    lang_instruction = get_language_instruction(target_language)

                    st.write(f"Переводим текст на {target_language}...")
                    with st.spinner(f"Переводим на {target_language}..."):
                        system_prompt = f"""Вы профессиональный переводчик. {lang_instruction}"""
                        user_prompt = f"""Переведите следующий текст на {target_language} язык,
                        сохраняя оригинальный смысл, стиль и форматирование. Не добавляйте замечаний от переводчика.
                        Не добавляйте вступлений или заключений. {lang_instruction}"""

                        # Определяем размер текста в токенах
                        tokens = num_tokens_from_string(formatted_text)
                        st.write(f"Количество токенов в тексте: {tokens}")

                        translated_text = ""

                        # В зависимости от размера текста либо обрабатываем текст целиком, либо делим на чанки
                        if tokens < 16000:
                            translated_text = utils.generate_answer(system_prompt, user_prompt, formatted_text)
                        else:
                            st.write("Текст слишком большой, разбиваем на части для перевода...")
                            # Разбиваем текст на чанки
                            text_chunks = split_text(formatted_text, chunk_size=30000, chunk_overlap=1000)
                            st.write(f"Текст разбит на {len(text_chunks)} частей")
                            # Обрабатываем каждый чанк отдельно
                            translated_text = process_text_chunks(text_chunks, system_prompt, user_prompt)

                    # Определяем пути сохранения для переведенного текста
                    translated_output_txt = os.path.join(file_dir, f"{target_language}_{file_name}.txt")
                    translated_output_docx = os.path.join(file_dir, f"{target_language}_{file_name}.docx")

                    # Сохраняем переведенную транскрибацию
                    if save_txt:
                        with open(translated_output_txt, "w", encoding="utf-8") as f:
                            f.write(translated_text)
                        st.success(f"Перевод на {target_language} сохранен в TXT: {translated_output_txt}")

                    if save_docx:
                        save_text_to_docx(translated_text, translated_output_docx)
                        st.success(f"Перевод на {target_language} сохранен в DOCX: {translated_output_docx}")

                    st.success(f"Перевод на {target_language} завершен!")
                    with st.expander(f"Просмотреть текст на {target_language}", expanded=False):
                        st.write(translated_text)

                    # Создаем конспект, если эта опция выбрана
                    if create_handbook_option:
                        handbook_text, md_processed_text = create_handbook(
                            translated_text, file_dir, file_name, target_language, save_txt, save_docx)
                        st.session_state.last_processed_dir = file_dir
                        st.session_state.process_completed = True
                        if file_dir not in st.session_state.processed_dirs:
                            st.session_state.processed_dirs.append(file_dir)
                    else:
                        # Добавляем возможность скачивания файлов, если конспект не создается
                        st.session_state.last_processed_dir = file_dir
                        st.session_state.process_completed = True
                        if file_dir not in st.session_state.processed_dirs:
                            st.session_state.processed_dirs.append(file_dir)
                        create_download_buttons(file_dir)
            else:
                st.error("Не удалось получить транскрибацию от Whisper API")

    except Exception as e:
        st.error(f"Ошибка при обработке файла: {str(e)}")
    finally:
        # Удаляем временный файл
        os.unlink(tmp_file_path)

    return transcription, file_dir

# Функция для обработки YouTube видео
def process_youtube_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    downloader = YouTubeDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_youtube_url(url):
        st.error("Указанный URL не похож на ссылку YouTube видео.")
        return None, None, None
    video_id = downloader.get_video_id(url) or "video"
    file_name = f"youtube_{video_id}"

    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)

    # Сохраняем путь в состояние сессии
    st.session_state.last_processed_dir = file_dir
    st.session_state.processed_dirs.append(file_dir)

    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    with st.spinner("Загружаем аудио из YouTube видео..."):
        audio_file = downloader.download_audio(
            url=url,
            output_filename=file_name,
            progress_callback=update_progress
        )
    if not audio_file:
        st.error("Ошибка при загрузке аудио из YouTube видео.")
        return None, None, None
    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")
    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time
    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

    # Сохраняем оригинал в папку файла
    if save_txt:
        original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")

    # Унифицированная логика определения необходимости перевода
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский",
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский",
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}

    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"

    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)

    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")

    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст

    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")

    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    if save_txt:
        trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
        with open(trans_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language, save_txt, save_docx)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, handbook_text, md_processed_text
    else:
        # Добавляем возможность скачивания файлов, если конспект не создается
        create_download_buttons(file_dir)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, None, None

# Функция для обработки Instagram видео
def process_instagram_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    downloader = InstagramDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_instagram_url(url):
        st.error("Указанный URL не похож на ссылку Instagram видео.")
        return None, None, None
    shortcode = downloader.extract_shortcode(url) or "video"
    file_name = f"instagram_{shortcode}"

    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)

    # Сохраняем путь в состояние сессии
    st.session_state.last_processed_dir = file_dir
    st.session_state.processed_dirs.append(file_dir)

    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    with st.spinner("Загружаем аудио из Instagram видео..."):
        audio_file = downloader.download_audio(
            url=url,
            output_filename=file_name,
            progress_callback=update_progress
        )
    if not audio_file:
        st.error("Ошибка при загрузке аудио из Instagram видео.")
        return None, None, None
    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")
    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time
    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

    # Сохраняем оригинал в папку файла
    if save_txt:
        original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")

    # Унифицированная логика определения необходимости перевода
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский",
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский",
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}

    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"

    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)

    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")

    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст

    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")

    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    if save_txt:
        trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
        with open(trans_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language, save_txt, save_docx)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, handbook_text, md_processed_text
    else:
        # Добавляем возможность скачивания файлов, если конспект не создается
        create_download_buttons(file_dir)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, None, None

# Функция для обработки файлов с Яндекс Диска
def process_yandex_disk_files(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает аудио и видео файлы с Яндекс Диска

    Args:
        url: URL на Яндекс Диск (файл или папку)
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект

    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = YandexDiskDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_yandex_disk_url(url):
        st.error("Указанный URL не является ссылкой на Яндекс Диск.")
        return None, None, None

    # Отображаем прогресс загрузки
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)

    # Загружаем файлы с Яндекс Диска
    with st.spinner("Загружаем файлы с Яндекс Диска..."):
        downloaded_files = downloader.process_yandex_disk_url(url, progress_callback=update_progress)

    if not downloaded_files:
        st.error("Не удалось загрузить файлы с Яндекс Диска.")
        return None, None, None

    st.success(f"Успешно загружено файлов: {len(downloaded_files)}")

    # Обрабатываем каждый скачанный файл
    all_transcriptions = []
    all_handbooks = []
    all_processed_dirs = []  # Список директорий для итогового скачивания

    for file_path in downloaded_files:
        if file_path is None or not os.path.exists(file_path):
            st.warning(f"Пропускаем некорректный файл")
            continue

        file_name = Path(file_path).stem
        st.subheader(f"Обработка файла: {file_name}")

        # Создаем отдельную папку для файла в директории экспорта
        file_dir = os.path.join(save_path, file_name)
        os.makedirs(file_dir, exist_ok=True)
        all_processed_dirs.append(file_dir)  # Добавляем директорию в список

        # Сохраняем путь в состояние сессии
        st.session_state.last_processed_dir = file_dir
        st.session_state.processed_dirs.append(file_dir)

        # Получаем информацию об аудио файле
        try:
            audio = audio_info(file_path)
            st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
            st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
            st.write(f"Количество каналов: {audio.channels}")
        except Exception as e:
            st.error(f"Ошибка при анализе файла: {str(e)}")
            continue

        # Транскрибация аудио
        with st.spinner(f"Выполняем транскрибацию файла {file_name}..."):
            start_time = time.time()
            try:
                transcription, original_language = transcribe_audio_whisper(
                    audio_path=file_path,
                    file_title=file_name,
                    save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
                )
                transcription = utils.format_transcription_paragraphs(transcription)
                elapsed_time = time.time() - start_time
            except Exception as e:
                st.error(f"Ошибка при транскрибации: {str(e)}")
                continue

        st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

        # Сохраняем оригинал в папку файла
        if save_txt:
            original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
            with open(original_txt_path, "w", encoding="utf-8") as f:
                f.write(transcription)
            st.success(f"Оригинал TXT сохранен: {original_txt_path}")

        if save_docx:
            original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
            save_text_to_docx(transcription, original_docx_path)
            st.success(f"Оригинал Word сохранен: {original_docx_path}")

        # Добавляем в список всех транскрипций
        all_transcriptions.append((file_name, transcription, transcription))  # Временно добавляем без перевода

        # Определяем, нужен ли перевод
        # Словари для маппинга названий языков в коды и наоборот
        lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
        lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский",
                            "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский",
                            "de": "немецкий", "it": "итальянский", "pt": "португальский"}

        # Получаем код оригинального языка
        orig_lang_code = original_language.lower() if original_language else "unknown"

        # Дополнительная проверка для корейского и других языков
        if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
            # Повторно определяем язык из текста
            orig_lang_code = utils.detect_language(transcription)

        # Получаем код целевого языка
        target_lang_code = lang_map.get(target_language.lower(), "ru")

        # Всегда переводим с языка, отличного от целевого
        need_translate = orig_lang_code != target_lang_code
        translated_text = transcription  # По умолчанию используем оригинальный текст

        # Показываем информацию о языке оригинала для диагностики
        orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
        st.info(f"Определен язык оригинала: {orig_lang_name}")

        if need_translate:
            with st.spinner(f"Переводим транскрибацию файла {file_name} с {orig_lang_name} на {target_language}..."):
                translated_text = utils.translate_text_gpt(transcription, target_language)
            st.success(f"Перевод файла {file_name} завершён!")
            # Обновляем перевод в списке транскрипций
            all_transcriptions[-1] = (file_name, transcription, translated_text)
        else:
            st.info(f"Язык оригинала ({orig_lang_name}) для файла {file_name} совпадает с целевым языком ({target_language}). Перевод не требуется.")

        # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
        if save_txt:
            trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
            with open(trans_txt_path, "w", encoding="utf-8") as f:
                f.write(translated_text)
            st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

        if save_docx:
            trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
            save_text_to_docx(translated_text, trans_docx_path)
            st.success(f"Переведённый Word сохранен: {trans_docx_path}")

        # Выводим оба текста
        st.subheader("Оригинальная транскрибация")
        st.text_area("Оригинал", transcription, height=200)
        st.subheader(f"Транскрибация на {target_language.capitalize()}")
        st.text_area("Перевод", translated_text, height=200)

        # Создаём конспект по переводу
        handbook_text = None
        if create_handbook_option:
            # Используем оригинальное имя файла без префикса "Conspect_"
            try:
                handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language, save_txt, save_docx)
                all_handbooks.append((file_name, handbook_text, md_processed_text))
                st.success(f"Конспект для файла {file_name} успешно создан")
            except Exception as e:
                st.error(f"Ошибка при создании конспекта: {str(e)}")
        else:
            # Добавляем возможность скачивания файлов для текущего файла
            create_download_buttons(file_dir)

    # Если обработано несколько файлов, предлагаем возможность скачать все результаты в одном ZIP-архиве
    if len(all_processed_dirs) > 1:
        st.header("📦 Скачать результаты всех обработанных файлов")

        try:
            # Создаем буфер для архива в памяти
            zip_buffer = BytesIO()

            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for dir_path in all_processed_dirs:
                    # Получаем название папки файла (последняя часть пути)
                    dir_name = os.path.basename(dir_path)

                    # Добавляем все файлы из директории в архив
                    for file_name in os.listdir(dir_path):
                        file_path = os.path.join(dir_path, file_name)
                        if os.path.isfile(file_path):
                            # Сохраняем с относительным путем, включающим имя директории
                            arc_name = os.path.join(dir_name, file_name)
                            zip_file.write(file_path, arcname=arc_name)

            zip_buffer.seek(0)  # перемещаем указатель в начало буфера

            st.download_button(
                label="📥 Скачать все результаты в одном архиве",
                data=zip_buffer,
                file_name="yandex_disk_results.zip",
                mime="application/zip",
                key=f"download_all_yandex_results"
            )
        except Exception as e:
            st.error(f"Ошибка при создании общего ZIP-архива: {str(e)}")

    # Возвращаем результаты для первого файла
    if len(all_transcriptions) > 0:
        st.session_state.last_processed_dir = all_processed_dirs[0]
    if all_processed_dirs[0] not in st.session_state.processed_dirs:
        st.session_state.processed_dirs.append(all_processed_dirs[0])
    st.session_state.process_completed = True

    if create_handbook_option and len(all_handbooks) > 0:
        return all_transcriptions[0][1], all_handbooks[0][1], all_handbooks[0][2]
    else:
        return all_transcriptions[0][1], None, None

# Функция для обработки Google Drive файлов
def process_gdrive_files(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает аудио и видео файлы с Google Drive

    Args:
        url: URL на Google Drive (файл или папку)
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект

    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = GoogleDriveDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_gdrive_url(url):
        st.error("Указанный URL не является ссылкой на Google Drive.")
        return None, None, None

    # Отображаем прогресс загрузки
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)

    # Загружаем файлы с Google Drive
    with st.spinner("Загружаем файлы с Google Drive..."):
        downloaded_files = downloader.process_gdrive_url(url, progress_callback=update_progress)

    if not downloaded_files:
        st.error("Не удалось загрузить файлы с Google Drive.")
        return None, None, None

    st.success(f"Успешно загружено файлов: {len(downloaded_files)}")

    # Обрабатываем каждый скачанный файл
    all_transcriptions = []
    all_handbooks = []
    all_processed_dirs = []  # Список директорий для итогового скачивания

    for file_path in downloaded_files:
        file_name = Path(file_path).stem
        st.subheader(f"Обработка файла: {file_name}")

        # Создаем отдельную папку для файла в директории экспорта
        file_dir = os.path.join(save_path, file_name)
        os.makedirs(file_dir, exist_ok=True)
        all_processed_dirs.append(file_dir)  # Добавляем в список обработанных директорий

        # Сохраняем путь в состояние сессии
        st.session_state.last_processed_dir = file_dir
        st.session_state.processed_dirs.append(file_dir)

        # Получаем информацию об аудио файле
        try:
            audio = audio_info(file_path)
            st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
            st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
            st.write(f"Количество каналов: {audio.channels}")
        except Exception as e:
            st.error(f"Ошибка при анализе файла: {str(e)}")
            continue

        # Транскрибация аудио
        with st.spinner(f"Выполняем транскрибацию файла {file_name}..."):
            start_time = time.time()
            try:
                transcription, original_language = transcribe_audio_whisper(
                    audio_path=file_path,
                    file_title=file_name,
                    save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
                )
                transcription = utils.format_transcription_paragraphs(transcription)
                elapsed_time = time.time() - start_time
            except Exception as e:
                st.error(f"Ошибка при транскрибации: {str(e)}")
                continue

        st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

        # Сохраняем оригинал в папку файла
        if save_txt:
            original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
            with open(original_txt_path, "w", encoding="utf-8") as f:
                f.write(transcription)
            st.success(f"Оригинал TXT сохранен: {original_txt_path}")

        if save_docx:
            original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
            save_text_to_docx(transcription, original_docx_path)
            st.success(f"Оригинал Word сохранен: {original_docx_path}")

        # Добавляем транскрипцию в список
        all_transcriptions.append((file_name, transcription))

        # Определяем, нужен ли перевод
        # Словари для маппинга названий языков в коды и наоборот
        lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
        lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский",
                            "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский",
                            "de": "немецкий", "it": "итальянский", "pt": "португальский"}

        # Получаем код оригинального языка
        orig_lang_code = original_language.lower() if original_language else "unknown"

        # Дополнительная проверка для корейского и других языков
        if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
            # Повторно определяем язык из текста
            orig_lang_code = utils.detect_language(transcription)

        # Получаем код целевого языка
        target_lang_code = lang_map.get(target_language.lower(), "ru")

        # Всегда переводим с языка, отличного от целевого
        need_translate = orig_lang_code != target_lang_code
        translated_text = transcription  # По умолчанию используем оригинальный текст

        # Показываем информацию о языке оригинала для диагностики
        orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
        st.info(f"Определен язык оригинала: {orig_lang_name}")

        if need_translate:
            with st.spinner(f"Переводим транскрибацию файла {file_name} с {orig_lang_name} на {target_language}..."):
                translated_text = utils.translate_text_gpt(transcription, target_language)
            st.success(f"Перевод файла {file_name} завершён!")
        else:
            st.info(f"Язык оригинала ({orig_lang_name}) для файла {file_name} совпадает с целевым языком ({target_language}). Перевод не требуется.")

        # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
        if save_txt:
            trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
            with open(trans_txt_path, "w", encoding="utf-8") as f:
                f.write(translated_text)
            st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

        if save_docx:
            trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
            save_text_to_docx(translated_text, trans_docx_path)
            st.success(f"Переведённый Word сохранен: {trans_docx_path}")

        # Выводим оба текста
        st.subheader("Оригинальная транскрибация")
        st.text_area("Оригинал", transcription, height=200)
        st.subheader(f"Транскрибация на {target_language.capitalize()}")
        st.text_area("Перевод", translated_text, height=200)

        # Создаём конспект по переводу
        handbook_text = None
        if create_handbook_option:
            # Используем оригинальное имя файла без префикса "Conspect_"
            try:
                handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language, save_txt, save_docx)
                all_handbooks.append((file_name, handbook_text, md_processed_text))
                st.success(f"Конспект для файла {file_name} успешно создан")
            except Exception as e:
                st.error(f"Ошибка при создании конспекта: {str(e)}")
        else:
            # Добавляем возможность скачивания файлов, если конспект не создается
            create_download_buttons(file_dir)

    # Если обработано несколько файлов, предлагаем возможность скачать все результаты в одном ZIP-архиве
    if len(all_processed_dirs) > 1:
        st.header("📦 Скачать результаты всех обработанных файлов")

        try:
            # Создаем буфер для архива в памяти
            zip_buffer = BytesIO()

            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for dir_path in all_processed_dirs:
                    # Получаем название папки файла (последняя часть пути)
                    dir_name = os.path.basename(dir_path)

                    # Добавляем все файлы из директории в архив
                    for file_name in os.listdir(dir_path):
                        file_path = os.path.join(dir_path, file_name)
                        if os.path.isfile(file_path):
                            # Сохраняем с относительным путем, включающим имя директории
                            arc_name = os.path.join(dir_name, file_name)
                            zip_file.write(file_path, arcname=arc_name)

            zip_buffer.seek(0)  # перемещаем указатель в начало буфера

            st.download_button(
                label="📥 Скачать все результаты в одном архиве",
                data=zip_buffer,
                file_name="google_drive_results.zip",
                mime="application/zip",
                key=f"download_all_gdrive_results"
            )
        except Exception as e:
            st.error(f"Ошибка при создании общего ZIP-архива: {str(e)}")

    # Исправляем возврат результатов - добавляем проверки на пустые списки
    # Если были созданы конспекты
    if create_handbook_option and len(all_handbooks) > 0:
        transcription = all_transcriptions[0][1] if len(all_transcriptions) > 0 else None
        return transcription, all_handbooks[0][1], all_handbooks[0][2]

    # Возвращаем результаты для первого файла
    if len(all_transcriptions) > 0:
        st.session_state.last_processed_dir = all_processed_dirs[0]
    if all_processed_dirs[0] not in st.session_state.processed_dirs:
        st.session_state.processed_dirs.append(all_processed_dirs[0])
    st.session_state.process_completed = True

    if create_handbook_option and len(all_handbooks) > 0:
        return all_transcriptions[0][1], all_handbooks[0][1], all_handbooks[0][2]
    else:
        return all_transcriptions[0][1], None, None

def process_vk_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает видео из ВКонтакте

    Args:
        url: URL на видео ВКонтакте
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект

    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = VKVideoDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_vk_url(url):
        st.error("Указанный URL не похож на ссылку на видео ВКонтакте.")
        return None, None, None

    # Нормализуем URL, чтобы обработать ссылки из разных источников
    url = downloader.normalize_vk_url(url)
    video_id = downloader.get_video_id(url) or "video"
    file_name = f"vk_video_{video_id}"

    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)

    # Сохраняем путь в состояние сессии
    st.session_state.last_processed_dir = file_dir
    st.session_state.processed_dirs.append(file_dir)

    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)

    with st.spinner("Загружаем аудио из видео ВКонтакте..."):
        audio_file = downloader.download_audio(
            url=url,
            output_filename=file_name,
            progress_callback=update_progress
        )

    if not audio_file:
        st.error("Ошибка при загрузке аудио из видео ВКонтакте.")
        return None, None, None

    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")

    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time

    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

    # Сохраняем оригинал в папку файла
    if save_txt:
        original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")

    # Определяем, нужен ли перевод
    # Словари для маппинга названий языков в коды и наоборот
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский",
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский",
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}

    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"

    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)

    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")

    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст

    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")

    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    if save_txt:
        trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
        with open(trans_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language, save_txt, save_docx)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, handbook_text, md_processed_text
    else:
        # Добавляем возможность скачивания файлов, если конспект не создается
        create_download_buttons(file_dir)
        st.session_state.last_processed_dir = file_dir
        if file_dir not in st.session_state.processed_dirs:
            st.session_state.processed_dirs.append(file_dir)
        st.session_state.process_completed = True
        return transcription, None, None

# --- Аутентификация по паролю через Streamlit secrets ---
def check_password():
    """Returns True if the user entered the correct password."""
    if "password_correct" in st.session_state:
        return st.session_state.password_correct
    import hmac
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if hmac.compare_digest(st.session_state.password, st.secrets.get("PASSWORD", "default_password")):
            st.session_state.password_correct = True
            del st.session_state.password  # Не храним пароль в сессии
        else:
            st.session_state.password_correct = False
    st.text_input(
        "Введите пароль для доступа к приложению", 
        type="password",
        key="password",
        on_change=password_entered
    )
    if "password_correct" in st.session_state:
        if not st.session_state.password_correct:
            st.error("😕 Неверный пароль")
            return False
    return False

# Если пароль неверный, остановить выполнение приложения
if not check_password():
    st.stop()

# Основная функция приложения
def main():
    st.title("🎤 Транскрибатор аудио и видео")
    st.markdown("### Преобразование аудио и видео в текст с помощью OpenAI Whisper API")

    # Проверяем, было ли завершено транскрибирование ранее
    if st.session_state.process_completed and st.session_state.last_processed_dir:
        st.success("✅ Обработка успешно завершена!")
        # Создаем кнопки для скачивания файлов последнего обработанного результата
        create_download_buttons(st.session_state.last_processed_dir)

        # Если есть другие обработанные директории, предлагаем их выбрать
        if len(st.session_state.processed_dirs) > 1:
            with st.expander("Другие обработанные результаты"):
                for dir_path in st.session_state.processed_dirs:
                    if dir_path != st.session_state.last_processed_dir:
                        if st.button(f"📂 Показать {os.path.basename(dir_path)}", key=f"show_{os.path.basename(dir_path)}"):
                            st.session_state.last_processed_dir = dir_path
                            st.rerun()  # Перезагружаем приложение для отображения другого результата

    # Боковая панель для опций
    with st.sidebar:
        st.header("Настройки")
        
        st.subheader("Язык транскрибации")
        target_language = st.selectbox(
            "Выберите язык для конечной транскрибации:",
            ["русский", "казахский", "английский"],
            index=0
        )

        # Удаляем выбор каталога сохранения, так как файлы будут сохраняться в предопределенные каталоги на сервере
        st.subheader("Файлы результатов")
        st.info("Результаты обработки можно будет скачать после завершения транскрибации.")

        # Используем стандартный путь для сохранения на сервере
        save_dir = TRANSCRIPTIONS_DIR

        st.subheader("Опции сохранения")
        save_txt = st.checkbox("Сохранить в TXT", value=False)
        save_docx = True  # DOCX всегда сохраняется
        create_handbook = True  # Конспект всегда создается

        # Добавляем возможность очистить результаты предыдущих транскрибаций
        if st.session_state.process_completed:
            if st.button("🗑️ Очистить предыдущие результаты"):
                st.session_state.process_completed = False
                st.session_state.last_processed_dir = None
                st.session_state.processed_dirs = []
                st.success("Результаты очищены!")
                st.rerun()

    # Основной контент с добавленной вкладкой VK video
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Локальные файлы",
        "YouTube",
        "VK видео",
        "Instagram",
        "Яндекс Диск",
        "Google Диск"
    ])

    # Вкладка для локальных файлов
    with tab1:
        st.header("Загрузить локальный файл")
        uploaded_files = st.file_uploader(
            "Выберите аудио или видео файлы",
            type=["mp3", "mp4", "wav", "m4a", "avi", "mov"],
            accept_multiple_files=True  # Включаем поддержку множественной загрузки
        )

        if uploaded_files:
            # Показываем счетчик загруженных файлов
            st.success(f"Загружено файлов: {len(uploaded_files)}")

            # Создаем аккордеон для просмотра каждого файла
            with st.expander("Просмотр загруженных файлов", expanded=False):
                for i, uploaded_file in enumerate(uploaded_files):
                    st.subheader(f"Файл #{i+1}: {uploaded_file.name}")
                    if uploaded_file.type.startswith('audio/') or uploaded_file.name.endswith(('.mp3', '.wav', '.m4a')):
                        st.audio(uploaded_file)
                    elif uploaded_file.type.startswith('video/') or uploaded_file.name.endswith(('.mp4', '.avi', '.mov')):
                        st.video(uploaded_file)

            if st.button("Транскрибировать выбранные файлы"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    # Обрабатываем каждый загруженный файл по очереди
                    for i, uploaded_file in enumerate(uploaded_files):
                        # Создаем разделитель между файлами
                        if i > 0:
                            st.markdown("---")

                        st.subheader(f"Обработка файла {i+1}/{len(uploaded_files)}: {uploaded_file.name}")

                        # Получаем название файла без расширения
                        file_name = Path(uploaded_file.name).stem

                        # Обрабатываем загруженный файл
                        process_uploaded_file(
                            uploaded_file,
                            save_dir,
                            file_name,
                            target_language,
                            save_txt=save_txt,
                            save_docx=True,
                            create_handbook_option=True
                        )

                    st.success(f"Обработка всех файлов завершена! Всего обработано: {len(uploaded_files)}")

    # Вкладка для YouTube
    with tab2:
        st.header("YouTube видео")
        youtube_url = st.text_input("Введите ссылку на YouTube видео", key="youtube_url")
        if youtube_url:
            if st.button("Транскрибировать YouTube видео"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_youtube_video(
                        youtube_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=True,
                        create_handbook_option=True
                    )

    # Новая вкладка для VK видео
    with tab3:
        st.header("VK видео")
        vk_url = st.text_input("Введите ссылку на видео ВКонтакте", key="vk_url")

        st.info("""
        Поддерживаются следующие типы ссылок:
        - Прямые ссылки на видео: https://vk.com/video-220754053_456243260
        - Ссылки из браузера: https://vk.com/vkvideo?z=video-220754053_456243260%2Fvideos-220754053%2Fpl_-220754053_-2
        """)

        if vk_url:
            if st.button("Транскрибировать VK видео"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_vk_video(
                        vk_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=True,
                        create_handbook_option=True
                    )

    # Вкладка для Instagram
    with tab4:
        st.header("Instagram видео")
        instagram_url = st.text_input("Введите ссылку на Instagram видео поста или reels", key="instagram_url")

        if instagram_url:
            if st.button("Транскрибировать Instagram видео"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_instagram_video(
                        instagram_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=True,
                        create_handbook_option=True
                    )

    # Вкладка для Яндекс Диск
    with tab5:
        st.header("Яндекс Диск")
        yandex_url = st.text_input("Введите ссылку на файл или папку на Яндекс Диске", key="yandex_url")

        if yandex_url:
            if st.button("Транскрибировать файлы с Яндекс Диска"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_yandex_disk_files(
                        yandex_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=True,
                        create_handbook_option=True
                    )

    # Вкладка для Google Диск
    with tab6:
        st.header("Google Диск")
        gdrive_url = st.text_input("Введите ссылку на файл или папку на Google Диске", key="gdrive_url")

        st.info("""
        Поддерживаются следующие типы ссылок:
        - Ссылки на файлы: https://drive.google.com/file/d/FILE_ID/view
        - Ссылки на папки: https://drive.google.com/drive/folders/FOLDER_ID

        Файлы и папки должны быть открыты для доступа по ссылке.
        """)

        if gdrive_url:
            if st.button("Транскрибировать файлы с Google Drive"):
                if not openai.api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_gdrive_files(
                        gdrive_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=True,
                        create_handbook_option=True
                    )

if __name__ == "__main__":
    main()
