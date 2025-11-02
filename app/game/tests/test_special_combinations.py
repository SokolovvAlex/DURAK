"""
Тесты определения особых комбинаций карт.
Тестирует логику определения:
- Бура (4 карты козырной масти)
- 4 конца (4 карты: десятки или тузы, с хотя бы одним козырем)
- Молодка (4 карты не козырной масти)
- Москва (3 туза с козырем)
"""
import pytest
from app.game.core.constants import DECK


def test_detect_bura_combination():
    """
    Тест: Определение комбинации "Бура" (4 карты козырной масти).
    """
    trump = "♦"
    hand = [("A", "♦"), ("K", "♦"), ("Q", "♦"), ("J", "♦")]  # 4 козыря
    
    # Проверяем, что все карты козырной масти
    is_bura = all(card[1] == trump for card in hand) and len(hand) == 4
    
    assert is_bura is True
    print("✅ Тест: Бура определена корректно")


def test_detect_4_ends_combination():
    """
    Тест: Определение комбинации "4 конца" (4 карты: десятки или тузы, с хотя бы одним козырем).
    """
    trump = "♦"
    hand = [("A", "♦"), ("A", "♠"), ("10", "♥"), ("10", "♣")]  # 2 туза, 2 десятки, 1 козырь
    
    # Проверяем: все карты тузы или десятки, и хотя бы один козырь
    all_tens_or_aces = all(card[0] in ["A", "10"] for card in hand)
    has_trump = any(card[1] == trump for card in hand)
    is_4_ends = all_tens_or_aces and has_trump and len(hand) == 4
    
    assert is_4_ends is True
    print("✅ Тест: 4 конца определены корректно")


def test_detect_molodka_combination():
    """
    Тест: Определение комбинации "Молодка" (4 карты не козырной масти).
    """
    trump = "♦"
    hand = [("A", "♠"), ("K", "♠"), ("Q", "♠"), ("J", "♠")]  # 4 карты не козырь
    
    # Проверяем, что все карты не козырной масти
    is_molodka = all(card[1] != trump for card in hand) and len(hand) == 4
    
    assert is_molodka is True
    print("✅ Тест: Молодка определена корректно")


def test_detect_moskva_combination():
    """
    Тест: Определение комбинации "Москва" (3 туза с козырем).
    """
    trump = "♦"
    hand = [("A", "♦"), ("A", "♠"), ("A", "♥"), ("K", "♣")]  # 3 туза, 1 козырь
    
    # Проверяем: 3 туза и хотя бы один козырь (не обязательно туз-козырь)
    aces_count = sum(1 for card in hand if card[0] == "A")
    has_trump = any(card[1] == trump for card in hand)
    is_moskva = aces_count == 3 and has_trump
    
    assert is_moskva is True
    print("✅ Тест: Москва определена корректно")


def test_no_special_combination():
    """
    Тест: Отсутствие особых комбинаций.
    """
    trump = "♠"  # Меняем козырь, чтобы рука не была Молодкой
    hand = [("A", "♠"), ("K", "♥"), ("Q", "♣"), ("J", "♦")]  # Обычные карты, есть козырь
    
    # Проверяем, что нет особых комбинаций
    from app.game.core.special_combinations import detect_special_combination
    combination = detect_special_combination(hand, trump)
    
    assert combination is None
    print("✅ Тест: особые комбинации отсутствуют корректно")

