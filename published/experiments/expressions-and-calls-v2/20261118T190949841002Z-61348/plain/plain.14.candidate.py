"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    if not words:
        return []

    average_word_length = sum(map(len, words)) / len(words)
    return [word for word in words if len(word) > average_word_length]
