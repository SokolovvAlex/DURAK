import pytest
import random
from app.game.core.durak import Durak


@pytest.fixture
def fixed_game():
    """Инициализируем игру с фиксированным seed, чтобы колода была предсказуемой"""
    rng = random.Random(42)
    game = Durak(rng=rng)
    return game


def test_game_initial_state(fixed_game):
    game = fixed_game
    print("\n=== СТАРТ ИГРЫ ===")
    print(f"Козырь: {game.trump}")
    print(f"Колода ({len(game.deck)} карт): {game.deck}")
    for i, player in enumerate(game.players):
        print(f"Игрок {i}, карты ({len(player.cards)}): {player.cards}")

    assert len(game.players) == 2
    assert all(len(p.cards) == 6 for p in game.players)


def test_attack_and_defend_flow(fixed_game):
    game = fixed_game
    attacker = game.current_player
    defender = game.opponent_player

    print("\n=== АТАКА ===")
    print(f"Атакующий (#{attacker.index}) до хода: {attacker.cards}")
    print(f"Защищающийся (#{defender.index}) до хода: {defender.cards}")

    # Берём первую карту атакующего
    attack_card = attacker.cards[0]
    ok = game.attack(attack_card)
    print(f"Атакующая карта: {attack_card}, результат: {ok}")
    print(f"Атакующий после хода: {attacker.cards}")
    print(f"Поле: {game.field}")

    assert ok is True
    assert attack_card not in attacker.cards

    # Попробуем защититься первой картой защитника
    defend_card = defender.cards[0]
    ok = game.defend(attack_card, defend_card)
    print(f"Защита картой: {defend_card}, результат: {ok}")
    print(f"Защищающийся после защиты: {defender.cards}")
    print(f"Поле: {game.field}")


def test_finish_turn(fixed_game):
    game = fixed_game

    # Делаем атаку для симуляции
    attack_card = game.current_player.cards[0]
    game.attack(attack_card)
    print("\n=== ЗАВЕРШЕНИЕ ХОДА ===")
    print(f"Поле перед завершением: {game.field}")

    result = game.finish_turn()
    print(f"Результат finish_turn(): {result}")
    for i, player in enumerate(game.players):
        print(f"Игрок {i} ({len(player.cards)} карт): {player.cards}")

    assert result in [Durak.NORMAL, Durak.TOOK_CARDS, Durak.GAME_OVER]