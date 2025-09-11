import pytest
from app.game.core.burkozel import Burkozel
from app.game.core.constants import SPADES, HEARTS, DIAMS, CLUBS


def test_init_game():
    game = Burkozel()
    print("=== Инициализация игры ===")
    print("Козырь:", game.trump)
    for i, p in enumerate(game.players):
        print(f"Игрок {i} карты: {p.cards}")
    assert len(game.players[0].cards) == 4
    assert len(game.players[1].cards) == 4
    assert game.trump in [SPADES, HEARTS, DIAMS, CLUBS]


def test_simple_attack_and_defense():
    game = Burkozel()
    # задаём простые руки
    game.players[0].cards = [("7", HEARTS)]
    game.players[1].cards = [("10", HEARTS)]
    game.field = {"attack": None, "defend": None, "winner": None}

    print("\n=== Атака одной картой ===")
    game.play(0, [("7", HEARTS)])
    print("Поле после атаки:", game.field)

    print("=== Защита одной картой ===")
    game.play(1, [("10", HEARTS)])
    print("Поле после защиты:", game.field)
    print("Очки:", game.round_scores)

    assert game.round_scores[1] == 10 + 0  # десятка 10 + семёрка 0


def test_invalid_attack():
    game = Burkozel()
    # две карты разных мастей без комбинации
    cards = [("7", HEARTS), ("8", SPADES)]
    print("\n=== Неверная атака (разные масти, не комбинация) ===")
    with pytest.raises(ValueError):
        game.play(0, cards)


def test_invalid_defense():
    game = Burkozel()
    game.trump = DIAMS
    game.players[0].cards = [("7", HEARTS)]
    game.players[1].cards = [("8", SPADES)]
    game.field = {"attack": None, "defend": None, "winner": None}

    game.play(0, [("7", HEARTS)])
    print("\n=== Слабая защита (положил ♠ против ♥) ===")
    game.play(1, [("8", SPADES)])  # положил карту другой масти

    # проверяем результат
    print("Очки:", game.round_scores)

    # победил атакующий (игрок 0)
    assert game.attacker_index == 0
    assert game.round_scores[0] == 0  # очков нет, потому что 7♥ и 8♠ ничего не стоят


def test_combo_bura():
    game = Burkozel()
    game.trump = SPADES
    cards = [("6", SPADES), ("7", SPADES), ("8", SPADES), ("9", SPADES)]
    assert game._is_combo(cards) == "bura"
    print("\n=== Проверка комбинации Бура ===", cards)


def test_combo_molodka():
    game = Burkozel()
    cards = [("6", HEARTS), ("7", HEARTS), ("8", HEARTS), ("9", HEARTS)]
    assert game._is_combo(cards) == "molodka"
    print("\n=== Проверка комбинации Молодка ===", cards)


def test_combo_moskva():
    game = Burkozel()
    game.trump = DIAMS
    cards = [("A", HEARTS), ("A", CLUBS), ("A", DIAMS)]
    assert game._is_combo(cards) == "moskva"
    print("\n=== Проверка комбинации Москва ===", cards)


def test_combo_4_ends_aces():
    game = Burkozel()
    cards = [("A", SPADES), ("A", HEARTS), ("A", DIAMS), ("A", CLUBS)]
    assert game._is_combo(cards) == "4-aces"
    print("\n=== Проверка комбинации 4 конца (тузы) ===", cards)


def test_combo_4_ends_tens():
    game = Burkozel()
    cards = [("10", SPADES), ("10", HEARTS), ("10", DIAMS), ("10", CLUBS)]
    assert game._is_combo(cards) == "4-tens"
    print("\n=== Проверка комбинации 4 конца (десятки) ===", cards)


def test_finish_trick_winner_attack():
    game = Burkozel()
    game.trump = DIAMS
    game.players[0].cards = [("A", HEARTS)]
    game.players[1].cards = [("K", HEARTS)]
    game.field = {"attack": None, "defend": None, "winner": None}

    game.play(0, [("A", HEARTS)])  # атака тузом
    game.play(1, [("K", HEARTS)])  # защита королём, но он слабее туза

    print("\n=== Завершение взятки: победил атакующий ===")
    print("Очки:", game.round_scores)
    assert game.round_scores[0] > 0


def test_finish_trick_winner_defender():
    game = Burkozel()
    game.trump = DIAMS
    game.players[0].cards = [("K", HEARTS)]
    game.players[1].cards = [("A", HEARTS)]
    game.field = {"attack": None, "defend": None, "winner": None}

    game.play(0, [("K", HEARTS)])  # атака королём
    game.play(1, [("A", HEARTS)])  # защита тузом
    print("\n=== Завершение взятки: победил защитник ===")
    print("Очки:", game.round_scores)
    assert game.round_scores[1] > 0
