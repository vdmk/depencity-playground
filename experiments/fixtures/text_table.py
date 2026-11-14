"""Format plain-text tables with ragged rows and multiline cells."""


def format_table(rows, headers=None):
    rows = [list(row) for row in rows]
    if headers is not None:
        rows.insert(0, list(headers))
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    if columns == 0:
        return ""
    cells = []
    widths = [0] * columns
    for row in rows:
        converted = []
        for column in range(columns):
            value = row[column] if column < len(row) else ""
            lines = str(value).split("\n")
            converted.append(lines)
            for line in lines:
                widths[column] = max(widths[column], len(line))
        cells.append(converted)
    output = []
    for index, row in enumerate(cells):
        height = max(len(cell) for cell in row)
        for line_index in range(height):
            parts = []
            for column, cell in enumerate(row):
                text = cell[line_index] if line_index < len(cell) else ""
                parts.append(text.ljust(widths[column]))
            output.append(" | ".join(parts).rstrip())
        if index == 0 and headers is not None:
            output.append("-+-".join("-" * width for width in widths))
    return "\n".join(output)
