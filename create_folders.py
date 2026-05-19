from pathlib import Path

base = Path(r"C:\Users\brady\OneDrive\Desktop\nfl-tools\player props\data\raw\pff")

for year in range(2021, 2026):
    for week in range(1, 23):
        folder = base / str(year) / f"week_{week:02d}"
        folder.mkdir(parents=True, exist_ok=True)

print("Folders created.")