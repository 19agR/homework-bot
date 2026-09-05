"""Telegram-бот для отслеживания статуса домашних работ Практикума."""

import logging
import os
import sys
import time
from http import HTTPStatus

import requests
import telebot
from dotenv import load_dotenv
from telebot.apihelper import ApiException


load_dotenv()


PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
REQUEST_TIMEOUT = 10


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


logger = logging.getLogger(__name__)


class MissingTokensError(Exception):
    """Не заданы обязательные переменные окружения для запуска бота."""


class UnexpectedStatusCodeError(Exception):
    """API Практикума вернул неожиданный HTTP-статус."""


def check_tokens():
    """Проверить переменные окружения или прервать запуск исключением."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    missing_tokens = [name for name, value in tokens.items() if not value]
    if missing_tokens:
        message = (
            'Отсутствуют обязательные переменные окружения: '
            f'{", ".join(missing_tokens)}. Запуск бота остановлен.'
        )
        logger.critical(message)
        raise MissingTokensError(message)


def send_message(bot, message):
    """Отправить сообщение в Telegram и записать результат в журнал."""
    logger.debug(f'Начало отправки сообщения в Telegram: {message!r}')
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except (ApiException, requests.RequestException) as error:
        logger.error(
            f'Сбой при отправке сообщения {message!r} в Telegram: {error}'
        )
        return False
    logger.debug(f'Бот отправил сообщение {message!r}')
    return True


def get_api_answer(timestamp):
    """Получить от API обновления, появившиеся после timestamp."""
    request_params = {
        'headers': HEADERS,
        'params': {'from_date': timestamp},
        'timeout': REQUEST_TIMEOUT,
    }
    log_params = {
        **request_params,
        'headers': {'Authorization': 'OAuth <скрыт>'},
    }
    logger.debug(
        f'Начало запроса к API: {ENDPOINT}; '
        'заголовки: {headers}; параметры: {params}; '
        'таймаут: {timeout} с.'.format(**log_params)
    )
    try:
        response = requests.get(ENDPOINT, **request_params)
    except requests.RequestException as error:
        raise ConnectionError(
            f'Ошибка при запросе к эндпоинту {ENDPOINT}: {error}'
        ) from error

    if response.status_code != HTTPStatus.OK:
        raise UnexpectedStatusCodeError(
            f'Эндпоинт {ENDPOINT} вернул неожиданный код ответа: '
            f'{response.status_code}. Ожидался {HTTPStatus.OK.value}.'
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
        raise TypeError(
            'Ответ API должен быть словарем (dict), '
            f'получен {type(response).__name__}.'
        )
    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks".')
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            'Значение ключа "homeworks" должно быть списком (list), '
            f'получен {type(homeworks).__name__}.'
        )
    if 'current_date' not in response:
        logger.warning(
            'В ответе API отсутствует ключ "current_date". '
            'Сохранена предыдущая временная метка.'
        )
    elif type(response['current_date']) is not int:
        raise TypeError(
            'Значение ключа "current_date" должно быть целым числом (int), '
            f'получен {type(response["current_date"]).__name__}.'
        )
    return homeworks


def parse_status(homework):
    """Подготовить сообщение о статусе одной домашней работы."""
    if not isinstance(homework, dict):
        raise TypeError(
            'Данные о домашней работе должны быть словарем (dict), '
            f'получен {type(homework).__name__}.'
        )
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
    check_tokens()

    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_error = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                if send_message(bot, message):
                    timestamp = response.get('current_date', timestamp)
            else:
                logger.debug('Новых статусов домашних работ нет.')
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if message != last_error:
                if send_message(bot, message):
                    last_error = message
        else:
            last_error = None
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='{asctime} [{levelname}] {message}',
        style='{',
        handlers=(logging.StreamHandler(sys.stdout),),
    )
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    try:
        main()
    except MissingTokensError:
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('Работа бота остановлена пользователем.')
        sys.exit(0)
