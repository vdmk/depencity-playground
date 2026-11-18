"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Return words longer than the average, preserving order and duplicates."""
    words = sentence.split()
    if not words:
        return []

    count = len(words)
    total_length = sum(map(len, words))
    result_count = 0
    for word in words:
        word_length = len(word)
        if word_length * count > total_length:
            words[result_count] = word
            result_count += 1
    del words[result_count:]
    return words
