"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    if len(words) == 0:
        return []

    average_length = sum(map(len, words)) / len(words)
    return [word for word in words if len(word) > average_length]
