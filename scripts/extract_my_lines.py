"""
Extracts only YOUR lines from a WhatsApp .txt export, dropping media
placeholders ("<Media omitted>", voice notes, deleted messages, etc.).

This does NOT anonymize or curate anything — it just narrows a full export
down to a numbered candidate list for you to read and hand-pick from.
Nothing here is meant to be used as-is; see the "manually review" step.

Usage (one or more export files at once):
    python extract_my_lines.py "Your Name" candidates.txt export1.txt export2.txt ...

"Your Name" must match exactly how your name appears in the exports
(check a couple of lines in the .txt file first if unsure — if it's spelled
differently across chats, run the script once per differently-spelled name
and merge the output files yourself).
"""
import os
import re
import sys

# Matches both common export formats:
#   Android: "9/15/26, 10:03 PM - Shahd: message text"
#   iOS:     "[9/15/26, 10:03:12 PM] Shahd: message text"
LINE_START = re.compile(
    r"^(?:\[)?\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]?M?\]?\s*[-–]?\s*"
    r"(?P<sender>[^:]+):\s*(?P<message>.*)$"
)

PLACEHOLDER_PATTERNS = [
    r"<Media omitted>",
    r"image omitted",
    r"video omitted",
    r"audio omitted",
    r"sticker omitted",
    r"GIF omitted",
    r"document omitted",
    r"This message was deleted",
    r"You deleted this message",
    r"‎?Missed voice call",
    r"‎?Missed video call",
]
PLACEHOLDER_RE = re.compile("|".join(PLACEHOLDER_PATTERNS), re.IGNORECASE)


def extract(export_path: str, my_name: str) -> list[str]:
    lines_out = []
    current_sender = None
    current_message_parts: list[str] = []

    def flush():
        if current_sender == my_name and current_message_parts:
            msg = " ".join(current_message_parts).strip()
            if msg and not PLACEHOLDER_RE.search(msg):
                lines_out.append(msg)

    with open(export_path, encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.rstrip("\n")
            match = LINE_START.match(raw_line)
            if match:
                flush()
                current_sender = match.group("sender").strip()
                current_message_parts = [match.group("message")]
            else:
                # continuation of a multi-line message
                if current_message_parts:
                    current_message_parts.append(raw_line)
        flush()

    return lines_out


def main():
    if len(sys.argv) < 4:
        print('Usage: python extract_my_lines.py "Your Name" candidates.txt export1.txt [export2.txt ...]')
        sys.exit(1)

    my_name, out_path, export_paths = sys.argv[1], sys.argv[2], sys.argv[3:]

    total = 0
    with open(out_path, "w", encoding="utf-8") as out_f:
        for export_path in export_paths:
            source = os.path.basename(export_path)
            lines = extract(export_path, my_name)
            for line in lines:
                total += 1
                out_f.write(f"{total}. [{source}] {line}\n")
            print(f"  {source}: {len(lines)} lines extracted")

    print(f"\nExtracted {total} of your lines total (media/placeholders excluded).")
    print(f"Written to {out_path} — the [source] tag helps you anonymize correctly per chat.")
    print("Now go read it and hand-pick ~15-20 good examples across all sources.")


if __name__ == "__main__":
    main()