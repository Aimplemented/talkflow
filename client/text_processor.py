"""
TalkFlow — Text Post-Processor
==============================
Fixes common Whisper transcription spacing and capitalization issues.
"""

import re


def clean_transcription(text: str) -> str:
    """
    Clean up common Whisper transcription issues.

    Fixes:
      - Add space after period/question/exclamation if followed by letter
      - Add space after comma if followed by letter
      - Capitalize first letter after period + space
      - Strip leading/trailing whitespace

    Parameters
    ----------
    text : str
        Raw transcription text from Whisper.

    Returns
    -------
    str
        Cleaned transcription text.

    Examples
    --------
    >>> clean_transcription("Hello world.This is a test")
    'Hello world. This is a test'
    >>> clean_transcription("First,second,third")
    'First, second, third'
    >>> clean_transcription("Done. next sentence")
    'Done. Next sentence'
    """
    if not text:
        return text

    # Strip leading/trailing whitespace
    text = text.strip()

    if not text:
        return text

    # Add space after sentence-ending punctuation if followed by a letter
    # Handles: period, question mark, exclamation mark
    text = re.sub(r'([.?!])([A-Za-z])', r'\1 \2', text)

    # Add space after comma if followed by a letter
    text = re.sub(r',([A-Za-z])', r', \1', text)

    # Add space after colon if followed by a letter (common in speech)
    text = re.sub(r':([A-Za-z])', r': \1', text)

    # Add space after semicolon if followed by a letter
    text = re.sub(r';([A-Za-z])', r'; \1', text)

    # Capitalize first letter after period + space
    def capitalize_after_period(match):
        return match.group(1) + match.group(2).upper()

    text = re.sub(r'(\. )([a-z])', capitalize_after_period, text)

    # Also capitalize after question mark + space
    text = re.sub(r'(\? )([a-z])', capitalize_after_period, text)

    # Also capitalize after exclamation + space
    text = re.sub(r'(! )([a-z])', capitalize_after_period, text)

    # Capitalize the very first character if it's lowercase
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # Normalize multiple spaces to single space
    text = re.sub(r' +', ' ', text)

    return text


if __name__ == "__main__":
    # Quick tests
    test_cases = [
        ("Hello world.This is a test", "Hello world. This is a test"),
        ("First,second,third", "First, second, third"),
        ("Done. next sentence", "Done. Next sentence"),
        ("what?really!", "What? Really!"),
        ("  spaces  around  ", "Spaces around"),
        ("Item1:value Item2:value", "Item1: value Item2: value"),
        ("normal text here", "Normal text here"),
        ("", ""),
        ("A.B.C", "A. B. C"),
    ]

    print("Testing clean_transcription():")
    for input_text, expected in test_cases:
        result = clean_transcription(input_text)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {input_text!r} -> {result!r}")
        if result != expected:
            print(f"         Expected: {expected!r}")
