"""Find words longer than the average word in a sentence."""


def long_words(sentence: str) -> list[str]:
    """Split on whitespace and preserve punctuation, order, and duplicates."""
    words = sentence.split()
    word_count = len(words)
    total_word_length = sum(map(len, words))
    return [
        word
        for word in words
        if len(word) * word_count > total_word_length
    ]
