# масти
SPADES = "♠"
HEARTS = "♥"
DIAMS = "♦"
CLUBS = "♣"

# достоинства карт
NOMINALS = ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]

# поиск индекса по достоинству
NAME_TO_VALUE = {n: i for i, n in enumerate(NOMINALS)}

# карт в руке при раздаче
CARDS_IN_HAND_MAX = 4
N_PLAYERS = 2

CARD_POINTS = {
    "A": 11,
    "10": 10,
    "K": 4,
    "Q": 3,
    "J": 2,
    "9": 0,
    "8": 0,
    "7": 0,
    "6": 0,
}


# эталонная колода (36 карт)
DECK = [(nom, suit) for nom in NOMINALS for suit in [SPADES, HEARTS, DIAMS, CLUBS]]
