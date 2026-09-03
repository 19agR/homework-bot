"""Telegram-бот для отслеживания статуса домашних работ Практикума."""

import logging
import os
import sys
import time
from http import HTTPStatus

import requests
import telebot
from dotenv import load_dotenv


load_dotenv()


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
REQUEST_TIMEOUT = 10


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру все понравилось. Ура!!',
    'reviewing': 'Работа взята на проверку ревьюером...',
    'rejected': 'Работа проверена: у ревьюера есть замечания :c'
}


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=(logging.StreamHandler(sys.stdout),),
)
logger = logging.getLogger(__name__)


def check_tokens():
    """Проверить наличие обязательных переменных окружения."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    missing_tokens = [name for name, value in tokens.items() if not value]
    for token_name in missing_tokens:
        logger.critical(
            'Отсутствует обязательная переменная окружения: %r',
            token_name,
        )
    return not missing_tokens


def send_message(bot, message):
    """Отправить сообщение в Telegram и записать результат в журнал."""
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as error:
        logger.error(
            'Сбой при отправке сообщения %r в Telegram: %s',
            message,
            error,
        )
        return False
    logger.debug('Бот отправил сообщение %r', message)
    return True


def get_api_answer(timestamp):
    """Получить от API обновления, появившиеся после timestamp."""
    params = {'from_date': timestamp}
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise ConnectionError(
            f'Ошибка при запросе к эндпоинту {ENDPOINT}: {error}'
        ) from error

    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )

    try:
        return response.json()
    except (TypeError, ValueError) as error:
        raise ValueError(
            'Не удалось преобразовать ответ API из формата JSON.'
        ) from error


def check_response(response):
    """Проверить структуру ответа API и вернуть список домашних работ."""
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарем.')
    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks".')
    if 'current_date' not in response:
        raise KeyError('В ответе API отсутствует ключ "current_date".')

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            'Значение ключа "homeworks" в ответе API должно быть списком.'
        )
    if not isinstance(response['current_date'], int):
        raise TypeError(
            'Значение ключа "current_date" в ответе API должно быть числом.'
        )
    return homeworks


def parse_status(homework):
    """Подготовить сообщение о статусе одной домашней работы."""
    if not isinstance(homework, dict):
        raise TypeError('Данные о домашней работе должны быть словарем.')
    if 'homework_name' not in homework:
        raise KeyError(
            'В данных о домашней работе отсутствует ключ "homework_name".'
        )
    if 'status' not in homework:
        raise KeyError(
            'В данных о домашней работе отсутствует ключ "status".'
        )

    homework_name = homework['homework_name']
    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус домашней работы: {status!r}.')
    verdict = HOMEWORK_VERDICTS[status]

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Запустить основной цикл работы бота."""
    if not check_tokens():
        logger.critical('Программа принудительно остановлена.')
        raise SystemExit(1)

    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_error = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                send_message(bot, message)
            else:
                logger.debug('Новых статусов домашних работ нет.')
            timestamp = response['current_date']
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if message != last_error:
                send_message(bot, message)
            last_error = message
        else:
            last_error = None
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
