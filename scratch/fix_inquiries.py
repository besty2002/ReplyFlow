"""Fix corrupted inquiries.html - line 34 broken div style + lines 66-68 duplicate section"""

import os

filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "templates", "inquiries.html")

with open(filepath, "rb") as f:
    raw = f.read()

lines = raw.split(b"\n")

print(f"Original line count: {len(lines)}")

# ── Fix 1: Line 34 (0-indexed 33) ──
# Current broken line:
#   <div style="display: flex; gap: 1                    <label class="form-label" ...
# Should be:
#   <div style="display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-end;">
#       <div class="form-group" style="margin: 0; min-width: 150px;">
#           <label class="form-label" ...

line34 = lines[33]
# Extract everything after the label opening tag (the Japanese text for ステータス + </label>)
split_marker = b'font-size: 0.75rem;">'
parts = line34.split(split_marker)
if len(parts) >= 2:
    label_content = split_marker + parts[1]
    new_line34 = (
        b'            <div style="display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-end;">\r\n'
        b'                <div class="form-group" style="margin: 0; min-width: 150px;">\r\n'
        b"                    <label class=\"form-label\" style=\"" + label_content
    )
    lines[33] = new_line34
    print("Fixed line 34: restored flex container and form-group wrapper")
else:
    print("WARNING: Could not find split marker in line 34")

# ── Fix 2: Lines 66-68 (0-indexed 65-67) ──
# These are a corrupted duplicate of the search button section.
# Line 67 contains a stray 0x80 byte making the file undecodable.
# Lines 69-71 have the clean version of this section.
# Remove the corrupted duplicate.

# Verify the corrupted line contains the stray byte
line67 = lines[66]
if b"\x80" in line67:
    del lines[65:68]
    print("Fixed lines 66-68: removed corrupted duplicate button section")
else:
    print("WARNING: Could not find stray 0x80 byte in expected line")

result = b"\n".join(lines)
print(f"New line count: {len(result.split(b'\n'))}")

with open(filepath, "wb") as f:
    f.write(result)

print("File saved successfully.")
