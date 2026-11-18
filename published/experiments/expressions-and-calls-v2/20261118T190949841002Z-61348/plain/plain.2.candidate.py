"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    if not words:
        return []

    word_count = len(words)
    total_length = sum(map(len, words))
    average_length = total_length / word_count
    return [word for word in words if len(word) > average_length]
