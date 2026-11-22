"""Sentence-aware splitting for speech generation."""
import re

def split_speech(text, engine, count):
    limit = min(600, 180 * count) if engine in ('clone', 'synthetic') else 1500
    pieces = []
    for paragraph in re.split(r'\n+', text):
        paragraph = paragraph.strip()
        if not paragraph: continue
        sentences = re.split(r'(?<=[.!?…])\s+(?=[^\s])', paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            while len(sentence) > limit:
                cut = sentence.rfind(' ', 0, limit + 1)
                if cut <= 0: cut = limit
                pieces.append((sentence[:cut].strip(), True))
                sentence = sentence[cut:].strip()
            if sentence: pieces.append((sentence, False))
    chunks, current, total = [], '', 0
    for part, forced in pieces:
        if current and len(current) + len(part) + 1 > limit:
            chunks.append(current); current = ''; total = 0
        current += (' ' if current else '') + part
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
