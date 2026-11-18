"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Return words longer than the average, preserving order and duplicates."""
    words = sentence.split()
    if not words:
        return []

    average_word_length = sum(map(len, words)) / len(words)
    kept = 0
    for word in words:
        if len(word) > average_word_length:
            words[kept] = word
            kept += 1
    del words[kept:]
    return words
