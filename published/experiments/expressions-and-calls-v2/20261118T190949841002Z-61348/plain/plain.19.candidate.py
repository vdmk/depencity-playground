"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Return words longer than the average, preserving order and duplicates."""
    words = sentence.split()
    if not words:
        return []

    word_count = len(words)
    total_length = sum(map(len, words))
    write_index = 0
    for word in words:
        word_length = len(word)
        if word_length * word_count > total_length:
            words[write_index] = word
            write_index += 1
    del words[write_index:]
    return words
