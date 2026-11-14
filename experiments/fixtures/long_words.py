"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    if not words:
        return []

    total_length = 0
    for word in words:
        total_length += len(word)
    average_length = total_length / len(words)

    result = []
    for word in words:
        if len(word) > average_length:
            result.append(word)
    return result
