"""
Функции для определения особых комбинаций карт в Буркозле.
"""
from app.game.core.constants import DECK


def detect_special_combination(hand: list[tuple[str, str]], trump: str) -> str | None:
    """
    Определяет особую комбинацию карт в руке игрока.
    
    Args:
        hand: Список карт в руке [(номинал, масть), ...]
        trump: Козырная масть
    
    Returns:
        Название комбинации или None если нет особой комбинации
    """
    if len(hand) != 4:
        return None
    
    # 1. Бура - 4 карты козырной масти
    if all(card[1] == trump for card in hand):
        return "bura"
    
    # Проверяем количество тузов
    aces = [card for card in hand if card[0] == "A"]
    aces_count = len(aces)
    
    # Проверяем наличие козыря
    has_trump = any(card[1] == trump for card in hand)
    
    # 2. Москва - 3 туза с козырем
    if aces_count == 3 and has_trump:
        return "moskva"
    
    # Проверяем десятки и тузы
    tens_and_aces = [card for card in hand if card[0] in ["A", "10"]]
    
    # 3. 4 конца - 4 карты: десятки или тузы, с хотя бы одним козырем
    if len(tens_and_aces) == 4 and has_trump:
        return "4_ends"
    
    # 4. Молодка - 4 карты не козырной масти
    if all(card[1] != trump for card in hand):
        return "molodka"
    
    return None


def has_special_combination(hand: list[tuple[str, str]], trump: str) -> bool:
    """
    Проверяет наличие особой комбинации в руке.
    
    Returns:
        True если есть особая комбинация, False если нет
    """
    return detect_special_combination(hand, trump) is not None

