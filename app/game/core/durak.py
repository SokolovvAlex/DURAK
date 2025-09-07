import random
from .constants import DECK, N_PLAYERS, NAME_TO_VALUE
from .utils import rotate
from .player import Player


class Durak:
    NORMAL = "normal"
    TOOK_CARDS = "took_cards"
    GAME_OVER = "game_over"

    def __init__(self, rng: random.Random = None):
        self.rng = rng or random.Random()
        self.deck = list(DECK)
        self.rng.shuffle(self.deck)

        self.players = [Player(i, []).take_cards_from_deck(self.deck) for i in range(N_PLAYERS)]

        self.trump = self.deck[0][1]
        self.deck = rotate(self.deck, -1)

        self.field = {}
        self.attacker_index = 0
        self.winner = None

    @property
    def attacking_cards(self):
        return list(filter(bool, self.field.keys()))

    @property
    def defending_cards(self):
        return list(filter(bool, self.field.values()))

    @property
    def any_unbeaten_card(self):
        return any(c is None for c in self.field.values())

    @property
    def current_player(self):
        return self.players[self.attacker_index]

    @property
    def opponent_player(self):
        return self.players[(self.attacker_index + 1) % N_PLAYERS]

    def attack(self, card):
        if self.winner:
            return False
        if not self.can_add_to_field(card):
            return False
        self.current_player.take_card(card)
        self.field[card] = None
        return True

    def can_add_to_field(self, card):
        if not self.field:
            return True
        for attack_card, defend_card in self.field.items():
            if self.card_match(attack_card, card) or self.card_match(defend_card, card):
                return True
        return False

    def card_match(self, card1, card2):
        if card1 is None or card2 is None:
            return False
        return card1[0] == card2[0]

    def defend(self, attacking_card, defending_card):
        if self.winner:
            return False
        if self.field[attacking_card] is not None:
            return False
        if self.can_beat(attacking_card, defending_card):
            self.field[attacking_card] = defending_card
            self.opponent_player.take_card(defending_card)
            return True
        return False

    def can_beat(self, card1, card2):
        nom1, suit1 = card1
        nom2, suit2 = card2
        nom1, nom2 = NAME_TO_VALUE[nom1], NAME_TO_VALUE[nom2]

        if suit2 == self.trump:
            return suit1 != self.trump or nom2 > nom1
        elif suit1 == suit2:
            return nom2 > nom1
        return False

    @property
    def attack_succeed(self):
        return any(def_card is None for def_card in self.field.values())

    def finish_turn(self):
        if self.winner:
            return self.GAME_OVER

        took_cards = False
        if self.attack_succeed:
            self._take_all_field()
            took_cards = True
        else:
            self.field = {}

        for p in rotate(self.players, self.attacker_index):
            p.take_cards_from_deck(self.deck)

        if not self.deck:
            for p in self.players:
                if not p.cards:
                    self.winner = p.index
                    return self.GAME_OVER

        if took_cards:
            return self.TOOK_CARDS
        else:
            self.attacker_index = self.opponent_player.index
            return self.NORMAL

    def _take_all_field(self):
        cards = self.attacking_cards + self.defending_cards
        self.opponent_player.add_cards(cards)
        self.field = {}