"""Sentence-aware splitting for speech generation."""
import re

SENTENCE_BOUNDARY = re.compile(r"""[.!?…]+[»”"’')\]]*(?=\s+\S)""")
NUMBERED_PREFIX = re.compile(r'(?:(?:глава|раздел|часть|пункт)\s+)?\d+(?:\.\d+)*\.(?=\s)', re.IGNORECASE)
LINE_PUNCTUATION = re.compile(r"""[.!?…,;:][»”"’')\]]*$""")


def prepare_speech_text(text):
    """Make line endings and dotted numbers explicit for the speech engine."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        prefix = NUMBERED_PREFIX.match(line)
        if prefix:
            end = prefix.end()
            line = line[:end - 1] + ',' + line[end:]
        line = re.sub(r'(?<=\d)\.(?=\d)', ' точка ', line)
        if not LINE_PUNCTUATION.search(line):
            line += '.'
        lines.append(line)
    return ' '.join(lines)


def split_speech(text, engine, count):
    limit = min(600, 180 * count) if engine in ('clone', 'synthetic') else 1500
    pieces = []
    for paragraph in re.split(r'\n+', text):
        paragraph = paragraph.strip()
        if not paragraph: continue
        prefix = NUMBERED_PREFIX.match(paragraph)
        start = 0
        ends = [match.end() for match in SENTENCE_BOUNDARY.finditer(paragraph)
                if prefix is None or match.end() != prefix.end()]
        separator = '\n'
        for end in [*ends, len(paragraph)]:
            sentence = paragraph[start:end]
            start = end
            sentence = sentence.strip()
            while len(sentence) > limit:
                cut = sentence.rfind(' ', 0, limit + 1)
                if cut <= 0: cut = limit
                pieces.append((sentence[:cut].strip(), True, separator))
                sentence = sentence[cut:].strip()
                separator = ' '
            if sentence:
                pieces.append((sentence, False, separator))
                separator = ' '
    chunks, current, total = [], '', 0
    for part, forced, separator in pieces:
        if current and len(current) + len(part) + 1 > limit:
            chunks.append(current); current = ''; total = 0
        current += (separator if current else '') + part
        total += 1
        if forced or (engine in ('clone', 'synthetic') and total >= count):
            chunks.append(current); current = ''; total = 0
    if current: chunks.append(current)
    return chunks


def split_document_speech(text, engine, count, headings):
    """Keep rendered headings separate from the body so playback can pause."""
    chunks, paragraph, pause_after = [], [], []
    for line in text.splitlines():
        if line.strip() not in headings:
            paragraph.append(line)
            continue
        chunks.extend(split_speech('\n'.join(paragraph), engine, count))
        paragraph.clear()
        title = split_speech(line, engine, count)
        if title:
            chunks.extend(title)
            pause_after.append(title[-1])
    chunks.extend(split_speech('\n'.join(paragraph), engine, count))
    return chunks, pause_after


def speech_resume_offset(text, chunks, completed):
    """Find the end of the prepared prefix in the original rendered text."""
    offset = resume = 0
    for index, chunk in enumerate(chunks, 1):
        pattern = re.compile(r'\s*' + r'\s+'.join(re.escape(word) for word in chunk.split()))
        match = pattern.match(text, offset)
        if match is None:
            return None
        offset = match.end()
        if index == completed:
            resume = offset
    return resume if not text[offset:].strip() else None
