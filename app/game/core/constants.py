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
CARDS_IN_HAND_MAX = 6
N_PLAYERS = 2

# эталонная колода (36 карт)
DECK = [(nom, suit) for nom in NOMINALS for suit in [SPADES, HEARTS, DIAMS, CLUBS]]
