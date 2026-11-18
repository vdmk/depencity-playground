"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    total_word_length = sum(map(len, words))
    average_length = total_word_length // (len(words) or 1)
    return [word for word in words if len(word) > average_length]
