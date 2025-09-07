def rotate(l, n: int):
    """Циклический сдвиг списка на n позиций."""
    return l[n:] + l[:n]
