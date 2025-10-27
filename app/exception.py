from fastapi import HTTPException, status


class BookingException(HTTPException):  # <-- наследуемся от HTTPException,
    status_code = 500  # <-- задаем значения по умолчанию
    detail = ""
    def __init__(self):
        super().__init__(status_code=self.status_code, detail=self.detail)


class UserAlreadyExistsException(BookingException):  # <-- обязательно наследуемся от нашего класса
    status_code = status.HTTP_409_CONFLICT
    detail = "Пользователь уже существует"


class IncorrectFormatTokenException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Не корректный формат токена"


class TokenExpireException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Токен истек"


class IncorrectEmailOrPasswordException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Не верный пароль или логин"


class NoPermissionsException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Нет доступа"


class UserIsNotPresentException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED


class NoTokenException(BookingException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Нет токена"


