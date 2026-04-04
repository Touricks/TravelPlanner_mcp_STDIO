"""Import risks, todos, and reservations from the Notion Markdown export.

Parses:
- 11 todo items (checkbox lines)
- 7 risks (2 markdown tables: Sequoia + Highway 1)
- 5 reservations (Advance Tickets table)
"""

import re
import sqlite3
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
TRIPDB_DIR = SEED_DIR.parent
MD_PATH = SEED_DIR / "sources" / "notion_export.md"
DB_PATH = TRIPDB_DIR / "travel.db"
TRIP_ID = "2026-04-san-francisco"


def parse_md_table(lines: list[str]) -> list[dict]:
    """Parse a markdown table into a list of dicts."""
    if len(lines) < 3:
        return []
    # Extract headers (strip bold markers)
    headers = [h.strip().strip('*') for h in lines[0].split('|')[1:-1]]
    rows = []
    for line in lines[2:]:  # skip header + separator
        line = line.strip()
        if not line or not line.startswith('|'):
            break
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def find_table_after(content: str, heading: str) -> list[dict]:
    """Find and parse the first markdown table after a heading line (### ...)."""
    lines = content.split('\n')
    in_section = False
    table_lines = []
    for line in lines:
        stripped = line.strip()
        # Only match heading lines (### ...), not body text
        if stripped.startswith('#') and heading.lower() in stripped.lower():
            in_section = True
            continue
        if in_section:
            if stripped.startswith('|'):
                table_lines.append(line)
            elif table_lines:
                break  # end of table
            elif stripped.startswith('#'):
                break  # hit next heading without finding a table
    return parse_md_table(table_lines)


def import_todos(conn: sqlite3.Connection, content: str):
    """Extract checkbox items and insert into todos."""
    cursor = conn.cursor()
    pattern = re.compile(r'- \[ \]\s+(.+)')
    count = 0
    for match in pattern.finditer(content):
        task = match.group(1).strip()

        # Assign priority
        task_lower = task.lower()
        if any(kw in task_lower for kw in ['book ', 'purchase', 'reserve']):
            priority = 'high'
        elif any(kw in task_lower for kw in ['create', 'pack lunch']):
            priority = 'low'
        else:
            priority = 'normal'

        # Assign category
        if any(kw in task_lower for kw in ['book', 'purchase', 'reserve', 'ticket']):
            category = 'booking'
        elif any(kw in task_lower for kw in ['chain', 'pack', 'tire', 'e-sim']):
            category = 'gear'
        else:
            category = 'logistics'

        cursor.execute("""
            INSERT INTO todos (trip_id, task, priority, category, source)
            VALUES (?, ?, ?, ?, 'md_export')
        """, (TRIP_ID, task, priority, category))
        count += 1

    conn.commit()
    print(f"  todos: {count} rows inserted")


def import_risks(conn: sqlite3.Connection, content: str):
    """Extract risk tables (Sequoia + Highway 1) and insert."""
    cursor = conn.cursor()
    count = 0

    # Category mapping
    category_map = {
        'tire chains': 'vehicle',
        'vehicle size': 'vehicle',
        'generals highway': 'road',
        'limited food': 'logistics',
        'landslide': 'road',
        'narrow winding': 'road',
        'no cell': 'logistics',
    }

    # Sequoia risks
    sequoia_rows = find_table_after(content, "Sequoia National Park")
    for row in sequoia_rows:
        risk_text = row.get('Risk', '').strip()
        detail = row.get('Detail', '').strip()
        action = row.get('Action Required', '').strip()

        # Determine category
        cat = 'logistics'
        for key, val in category_map.items():
            if key in risk_text.lower():
                cat = val
                break

        cursor.execute("""
            INSERT INTO risks (trip_id, category, risk, detail, action_required, source)
            VALUES (?, ?, ?, ?, ?, 'md_export')
        """, (TRIP_ID, cat, risk_text, detail, action))
        count += 1

    # Highway 1 risks
    hwy1_rows = find_table_after(content, "Highway 1 Big Sur")
    for row in hwy1_rows:
        risk_text = row.get('Risk', '').strip()
        detail = row.get('Detail', '').strip()
        action = row.get('Action Required', '').strip()

        cat = 'road'
        for key, val in category_map.items():
            if key in risk_text.lower():
                cat = val
                break

        cursor.execute("""
            INSERT INTO risks (trip_id, category, risk, detail, action_required, source)
            VALUES (?, ?, ?, ?, ?, 'md_export')
        """, (TRIP_ID, cat, risk_text, detail, action))
        count += 1

    conn.commit()
    print(f"  risks: {count} rows inserted")


def parse_cost(text: str) -> float | None:
    """Extract numeric cost from text like '$59.95/adult', 'Free', '$35/vehicle'."""
    if not text or 'free' in text.lower():
        return 0.0
    match = re.search(r'\$?([\d.]+)', text)
    return float(match.group(1)) if match else None


def import_reservations(conn: sqlite3.Connection, content: str):
    """Extract Advance Tickets table and insert as reservations."""
    cursor = conn.cursor()
    count = 0

    rows = find_table_after(content, "Advance Tickets")
    for row in rows:
        attraction = row.get('Attraction', '').strip()
        booking_req_text = row.get('Booking Required?', '').strip()
        booking_required = 0 if booking_req_text.lower().startswith('no') else 1
        cost_text = row.get('Cost', '').strip()
        cost = parse_cost(cost_text)
        book_ahead = row.get('Book How Far Ahead', '').strip()

        # Try to link to existing place
        place_row = cursor.execute(
            "SELECT id FROM places WHERE name_en LIKE ? LIMIT 1",
            (f"%{attraction.split('(')[0].strip()}%",)
        ).fetchone()
        place_id = place_row[0] if place_row else None

        cursor.execute("""
            INSERT INTO reservations (trip_id, place_id, attraction, booking_required,
                cost_per_person, cost_notes, book_ahead, booking_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'unbooked')
        """, (TRIP_ID, place_id, attraction, booking_required,
              cost, cost_text, book_ahead))
        count += 1

    conn.commit()
    print(f"  reservations: {count} rows inserted")


def import_md(conn: sqlite3.Connection):
    """Orchestrate MD import: todos + risks + reservations."""
    content = MD_PATH.read_text(encoding='utf-8')
    import_todos(conn, content)
    import_risks(conn, content)
    import_reservations(conn, content)


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    import_md(conn)
    conn.close()
