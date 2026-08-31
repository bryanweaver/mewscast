"""
Text truncation utilities for mewscast.
"""


def _truncate_at_sentence(text: str, max_length: int) -> str:
    """
    Truncate text at the last complete sentence that fits within max_length.
    Avoids mid-sentence cuts with '...' by finding natural break points.
    Falls back to dropping the last incomplete line if no sentence boundary found.
    """
    if len(text) <= max_length:
        return text

    truncated = text[:max_length]

    # Try to find the last sentence-ending punctuation that fits
    # Look for '. ', '! ', '? ', '.\n', '!\n', '?\n', or end-of-sentence at boundary
    best_cut = -1
    for i in range(len(truncated) - 1, 0, -1):
        if truncated[i] in '.!?' and (i == len(truncated) - 1 or truncated[i + 1] in ' \n'):
            best_cut = i + 1
            break
        # Also check for sentence ending right at a newline
        if truncated[i] == '\n' and i > 0 and truncated[i - 1] in '.!?':
            best_cut = i
            break

    if best_cut > max_length // 3:  # Only use if we keep at least 1/3 of content
        return truncated[:best_cut].rstrip()

    # Fallback: cut at last newline (drop the incomplete last line)
    last_newline = truncated.rfind('\n')
    if last_newline > max_length // 3:
        return truncated[:last_newline].rstrip()

    # Final fallback: cut at last space, no "..."
    last_space = truncated.rfind(' ')
    if last_space > max_length // 3:
        return truncated[:last_space].rstrip()

    return truncated.rstrip()
