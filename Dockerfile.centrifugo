FROM centrifugo/centrifugo:v6

# Устанавливаем рабочую директорию
WORKDIR /centrifugo

# Копируем конфигурационный файл
COPY config.json ./config.json

# Открываем порт 8000
EXPOSE 8000

# Запускаем Centrifugo с указанной конфигурацией
CMD ["centrifugo", "--config", "config.json"]