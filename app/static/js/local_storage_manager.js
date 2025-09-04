window.fakeStorage = {
    _data: {},

    setItem: function (id, val) {
        return this._data[id] = String(val);
    },

    getItem: function (id) {
        return this._data.hasOwnProperty(id) ? this._data[id] : undefined;
    },

    removeItem: function (id) {
        return delete this._data[id];
    },

    clear: function () {
        return this._data = {};
    }
};

LocalStorageManager.prototype.clearStorage = function () {
    this.storage.clear();
};

function LocalStorageManager() {
    this.bestScoreKey = "bestScore";
    this.gameStateKey = "gameState";

    var supported = this.localStorageSupported();
    this.storage = supported ? window.localStorage : window.fakeStorage;
}

LocalStorageManager.prototype.localStorageSupported = function () {
    var testKey = "test";

    try {
        var storage = window.localStorage;
        storage.setItem(testKey, "1");
        storage.removeItem(testKey);
        return true;
    } catch (error) {
        return false;
    }
};

// Best score getters/setters
LocalStorageManager.prototype.getBestScore = function () {
    // this.storage.clear();
    return this.storage.getItem(this.bestScoreKey) || 0;
};

LocalStorageManager.prototype.clearStorage = async function () {
    const userId = localStorage.getItem("userId");
    this.storage.clear();

    try {
        // Отправка нового результата на сервер
        const response = await fetch(`/api/bestScore/${userId}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({score: 0}) // Убедитесь, что это объект { score: <значение> }
        });

        if (response.ok) {
            const data = await response.json();
            console.log("Best score updated on server:", data.best_score);
        } else {
            console.error("Failed to update best score on server.");
        }
    } catch (error) {
        console.error("Error updating best score on server:", error);
    }
};

LocalStorageManager.prototype.setBestScore = async function (score) {
    this.storage.setItem(this.bestScoreKey, score);
    const userId = localStorage.getItem("userId");
    try {
        // Отправка нового результата на сервер
        const response = await fetch(`/api/bestScore/${userId}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({score: score}) // Убедитесь, что это объект { score: <значение> }
        });

        if (response.ok) {
            const data = await response.json();
            console.log("Best score updated on server:", data.best_score);
        } else {
            console.error("Failed to update best score on server.");
        }
    } catch (error) {
        console.error("Error updating best score on server:", error);
    }
};
// Game state getters/setters and clearing
LocalStorageManager.prototype.getGameState = function () {
    var stateJSON = this.storage.getItem(this.gameStateKey);
    return stateJSON ? JSON.parse(stateJSON) : null;
};

LocalStorageManager.prototype.setGameState = function (gameState) {
    this.storage.setItem(this.gameStateKey, JSON.stringify(gameState));
};

LocalStorageManager.prototype.clearGameState = function () {
    this.storage.removeItem(this.gameStateKey);
};

document.getElementById("clearStorageButton").addEventListener("click", function () {
    Telegram.WebApp.showConfirm("Вы уверены, что хотите очистить свой рекорд?", async function (confirmation) {
        if (confirmation) {
            const manager = new LocalStorageManager();
            await manager.clearStorage(); // Ждём завершения очистки

            Telegram.WebApp.showAlert("Ваш рекорд успешно очищен."); // Уведомление об успешной очистке
            location.reload(); // Перезагружаем страницу
        } else {
            Telegram.WebApp.showAlert("Очистка рекорда отменена."); // Уведомление об отмене
        }
    });
});
