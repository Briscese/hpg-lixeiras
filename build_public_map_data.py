"""Build static map data from the manually prepared coordinate workbook."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import openpyxl


SOURCES = {
    "Medição Manual": {"columns": (3, 4, 5), "detail": "Referência manual", "color": "#dc2626", "dashArray": "7 6"},
    "LL02": {"columns": (7, 8, None), "detail": "Última posição disponível", "color": "#7c3aed"},
    "LL303": {"columns": (10, 11, None), "detail": "Última posição disponível", "color": "#d97706"},
    "ATC700": {"columns": (13, 14, None), "detail": "Última posição válida", "color": "#087443"},
}
START = datetime(2026, 7, 31, 8, 0, 0)
END = datetime(2026, 7, 31, 12, 0, 0)


def parse_time(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    for format_string in ("%d/%m/%Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), format_string)
        except ValueError:
            pass
    raise ValueError(f"Data invalida: {value!r}")


def parse_coordinates(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str) or value == "Sem fix":
        return None
    try:
        latitude, longitude = (float(part.strip()) for part in value.split(","))
        return latitude, longitude
    except ValueError:
        return None


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\gabri\Downloads\Coodenadas Para o Site.xlsx")
    worksheet = openpyxl.load_workbook(input_path, data_only=True, read_only=True).active
    tracks = []

    for name, metadata in SOURCES.items():
        time_column, coordinate_column, longitude_column = metadata["columns"]
        points = []
        for row in worksheet.iter_rows(min_row=3, values_only=True):
            time_value = row[time_column]
            if not time_value:
                continue
            try:
                timestamp = parse_time(time_value)
            except ValueError:
                continue
            if not START <= timestamp <= END:
                continue
            if longitude_column is None:
                coordinates = parse_coordinates(row[coordinate_column])
            elif row[coordinate_column] is not None and row[longitude_column] is not None:
                coordinates = float(row[coordinate_column]), float(row[longitude_column])
            else:
                coordinates = None
            if coordinates:
                points.append([timestamp.strftime("%d/%m/%Y %H:%M:%S"), *coordinates])

        tracks.append({"name": name, "detail": metadata["detail"], "color": metadata["color"], "points": sorted(points)})
        if "dashArray" in metadata:
            tracks[-1]["dashArray"] = metadata["dashArray"]

    output = "const trackData = " + json.dumps(tracks, ensure_ascii=False, separators=(",", ":")) + ";\n"
    output_path = Path(__file__).with_name("docs") / "tracks.js"
    output_path.write_text(output, encoding="utf-8")
    print(f"Dados gerados: {output_path} ({sum(len(track['points']) for track in tracks)} pontos)")


if __name__ == "__main__":
    main()
