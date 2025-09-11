import random
from .constants import DECK, NAME_TO_VALUE, CARD_POINTS, CARDS_IN_HAND_MAX
from .player import Player
from .utils import rotate


class Burkozel:
    def __init__(self, rng: random.Random = None):
        self.rng = rng or random.Random()
        self.deck = list(DECK)
        self.rng.shuffle(self.deck)

        # раздаём по 4 карты
        self.players = [Player(i, []).add_cards(self.deck[:4]) for i in range(2)]
        del self.deck[:8]

        self.trump = self.deck[0][1]
        self.deck = rotate(self.deck, -1)

        self.field = {"attack": None, "defend": None, "winner": None}
        self.attacker_index = 0
        self.round_scores = {0: 0, 1: 0}
        self.penalties = {0: 0, 1: 0}

    # ======================
    # Вспомогательные методы
    # ======================

    def _card_points(self, card):
        return CARD_POINTS.get(card[0], 0)

    def _can_beat(self, atk, dfn):
        """Можно ли побить карту atk картой dfn?"""
        nom1, suit1 = atk
        nom2, suit2 = dfn

        if suit2 == suit1:  # та же масть
            return NAME_TO_VALUE[nom2] > NAME_TO_VALUE[nom1]
        if suit2 == self.trump and suit1 != self.trump:  # козырь против не-козыря
            return True
        return False

    # ======================
    # Комбинации
    # ======================

    def _is_combo(self, cards):
        if len(cards) == 4:
            # Бура (4 козыря)
            if all(c[1] == self.trump for c in cards):
                return "bura"

            # Молодка (4 одной масти, но не все козыри)
            if len(set(s for _, s in cards)) == 1:
                return "molodka"

            # 4 конца (4 туза или 4 десятки)
            if all(n == "A" for n, _ in cards):
                return "4-aces"
            if all(n == "10" for n, _ in cards):
                return "4-tens"

        if len(cards) == 3:
            # Москва (3 туза, включая козырного)
            if sum(1 for n, _ in cards if n == "A") == 3:
                if any(c == ("A", self.trump) for c in cards):
                    return "moskva"

        return None

    # ======================
    # Проверка ходов
    # ======================

    def _valid_attack(self, cards):
        """Ход: все одной масти или комбинация"""
        if len(set(s for _, s in cards)) == 1:
            return True
        return self._is_combo(cards) is not None

    def _valid_defense(self, cards):
        """Защита: главное, чтобы количество совпадало"""
        atk_cards = self.field["attack"]["cards"]
        return len(cards) == len(atk_cards)

    def _finish_trick(self):
        atk = self.field["attack"]
        dfn = self.field["defend"]

        # проверяем, побиты ли все карты
        beats_all = all(
            self._can_beat(atk_card, dfn_card)
            for atk_card, dfn_card in zip(atk["cards"], dfn["cards"])
        )

        if beats_all:
            winner = dfn["player"]
        else:
            winner = atk["player"]

        self.field["winner"] = winner
        self._add_points(winner, atk["cards"] + dfn["cards"])

        # следующий ходит победитель
        self.attacker_index = winner
        self.field = {"attack": None, "defend": None, "winner": None}

    # ======================
    # Игровой процесс
    # ======================

    def play(self, player_index, cards):
        """Игрок кладёт карты"""
        cards = list(cards)

        if self.field["attack"] is None:  # атака
            if not self._valid_attack(cards):
                raise ValueError("Нельзя ходить такими картами")
            self.players[player_index].remove_cards(cards)
            self.field["attack"] = {"player": player_index, "cards": cards}

        else:  # защита
            if not self._valid_defense(cards):
                raise ValueError("Неверная защита")
            self.players[player_index].remove_cards(cards)
            self.field["defend"] = {"player": player_index, "cards": cards}

        # если оба походили → определить победителя
        if self.field["attack"] and self.field["defend"]:
            self._finish_trick()

    def _add_points(self, player_index, cards):
        pts = sum(self._card_points(c) for c in cards)
        self.round_scores[player_index] += pts

    def __repr__(self):
        return f"Burkozel(trump={self.trump}, scores={self.round_scores})"
