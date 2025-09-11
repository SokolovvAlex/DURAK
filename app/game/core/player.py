from .constants import CARDS_IN_HAND_MAX, NAME_TO_VALUE, CARD_POINTS

class Player:
    def __init__(self, index, cards):
        self.index = index
        self.cards = list(map(tuple, cards))
        self.tricks = []   # список карт, которые игрок взял на взятках

    def take_cards_from_deck(self, deck: list, count: int = CARDS_IN_HAND_MAX):
        """Добирает карты из колоды."""
        lack = max(0, count - len(self.cards))
        n = min(len(deck), lack)
        self.add_cards(deck[:n])
        del deck[:n]
        return self

    def sort_hand(self):
        self.cards.sort(key=lambda c: (NAME_TO_VALUE[c[0]], c[1]))
        return self

    def add_cards(self, cards):
        self.cards += list(cards)
        self.sort_hand()
        return self

    def add_trick(self, cards):
        """Добавить карты из взятки к игроку"""
        self.tricks.extend(cards)

    def count_points(self):
        """Подсчитать очки игрока по всем взяткам"""
        return sum(CARD_POINTS[nom] for nom, _ in self.tricks)

    def remove_cards(self, cards):
        """Удалить список карт из руки"""
        for card in cards:
            if card not in self.cards:
                raise ValueError(f"У игрока нет карты {card}")
            self.cards.remove(card)
        return self

    def __repr__(self):
        return f"Player{self.cards!r}"

    def take_card(self, card):
        self.cards.remove(card)

    @property
    def n_cards(self):
        return len(self.cards)

    def __getitem__(self, item):
        return self.cards[item]