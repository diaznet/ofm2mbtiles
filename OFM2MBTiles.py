#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Code to convert a bounding box to an MBTiles file using OpenFlightMaps tile server.
"""

import asyncio
import aiohttp
import sqlite3
import mercantile
import argparse
from tqdm import tqdm
import os

CONCURRENT_REQUESTS = 10
RETRY_LIMIT = 3
TILE_SIZE = 512


def tms_y(z: int, y: int) -> int:
    """Convert XYZ Y to TMS Y coordinate.

    Args:
        z (int): Zoom level
        y (int): XYZ Y coordinate

    Returns:
        int: TMS Y coordinate
    """
    return (2**z - 1) - y


def create_mbtiles(
    path: str,
    bbox: list[float],
    min_zoom: int,
    max_zoom: int
) -> sqlite3.Connection:
    """Create an MBTiles SQLite database and set up schema and metadata.

    Args:
        path (str): Path to MBTiles file
        bbox (list[float]): Bounding box [min_lon, min_lat, max_lon, max_lat]
        min_zoom (int): Minimum zoom level
        max_zoom (int): Maximum zoom level

    Returns:
        sqlite3.Connection: SQLite connection object
    """

    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);")
    c.execute("""
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER,
            tile_column INTEGER,
            tile_row INTEGER,
            tile_data BLOB
        );
    """)
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);"
    )

    metadata = {
        "name": "Custom Area Tiles",
        "format": "png",
        "type": "baselayer",
        "version": "1.0",
        "bounds": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "tile_size": str(TILE_SIZE)
    }
    for k, v in metadata.items():
        c.execute("INSERT INTO metadata (name, value) VALUES (?, ?)", (k, v))

    conn.commit()
    return conn


async def download_tile(
    session: aiohttp.ClientSession,
    url: str,
    z: int,
    x: int,
    y: int
) -> tuple[int, int, int, bytes] | None:
    """Download a single tile with retries.

    Args:
        session (aiohttp.ClientSession): HTTP session
        url (str): Tile URL
        z (int): Zoom level
        x (int): Tile X
        y (int): Tile Y

    Returns:
        tuple[int, int, int, bytes] | None: (z, x, y, tile data) or None on failure
    """

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return z, x, y, await resp.read()
                else:
                    if attempt == RETRY_LIMIT:
                        print(f"❌ Failed {z}/{x}/{y}: HTTP {resp.status}")
        except Exception as e:
            if attempt == RETRY_LIMIT:
                print(f"⚠️  Error {z}/{x}/{y}: {e}")
        await asyncio.sleep(0.5 * attempt)  # exponential backoff
    return None


async def fetch_all_tiles(
    tiles: list[mercantile.Tile],
    bbox: list[float],
    airac_cycle: str,
    oaci_prefix: str,
    min_zoom: int,
    max_zoom: int,
    show_progress: bool
) -> None:
    """Download all tiles and store them in an MBTiles file.

    Args:
        tiles (list[mercantile.Tile]): List of tiles to download
        bbox (list[float]): Bounding box
        airac_cycle (str): AIRAC cycle string
        oaci_prefix (str): OACI prefix string
        min_zoom (int): Minimum zoom level
        max_zoom (int): Maximum zoom level
        show_progress (bool): Whether to show progress bar

    Returns:
        None
    """

    # --- Ensure folder exists ---
    mbtiles_folder = os.path.join("mbtiles", "")
    os.makedirs(mbtiles_folder, exist_ok=True)  # ✅ creates folder if missing

    # --- Create filename ---
    mbtiles_file = f"{oaci_prefix}_{airac_cycle}_zoom{min_zoom}-{max_zoom}.mbtiles"

    # --- Full path for MBTiles ---
    mbtiles_path = os.path.join(mbtiles_folder, mbtiles_file)

    # --- Create MBTiles ---
    conn = create_mbtiles(mbtiles_path, bbox, min_zoom, max_zoom)
    c = conn.cursor()

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    base_url_template = f"https://nwy-tiles-api.prod.newaydata.com/tiles/{{z}}/{{x}}/{{y}}.png?path={airac_cycle}/aero/latest"

    async with aiohttp.ClientSession() as session:
        async def sem_download(tile: mercantile.Tile) -> tuple[int, int, int, bytes] | None:
            async with semaphore:
                url = base_url_template.format(z=tile.z, x=tile.x, y=tile.y)
                return await download_tile(session, url, tile.z, tile.x, tile.y)

        tasks = [sem_download(tile) for tile in tiles]
        iterator = asyncio.as_completed(tasks)

        if show_progress:
            iterator = tqdm(iterator, total=len(tiles), desc="Downloading tiles", unit="tile")

        for future in iterator:
            result = await future
            if result:
                z, x, y, data = result
                c.execute(
                    "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    (z, x, tms_y(z, y), data),
                )

    conn.commit()
    conn.close()
    print(f"\n✅ MBTiles file created: {mbtiles_file}")


def main() -> None:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Generate an MBTiles file from OpenFlightMaps tile server for a given bounding box, zoom range, and AIRAC cycle."
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        required=True,
        help="Bounding box coordinates (min_lon min_lat max_lon max_lat)"
    )
    parser.add_argument(
        "--zoom",
        nargs=2,
        type=int,
        metavar=("MIN_ZOOM", "MAX_ZOOM"),
        default=[7, 12],
        help="Zoom level range (default: 7 12)"
    )
    parser.add_argument(
        "--airac",
        type=str,
        default="latest",
        help='AIRAC cycle number or "latest" (used in the tile URL, e.g. "2502" or "latest")'
    )
    parser.add_argument(
        "--oaci-prefix",
        type=str,
        default="latest",
        help='AIRAC cycle number or "latest" (used in the tile URL, e.g. "2502" or "latest")'
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress bar during downloads"
    )

    args = parser.parse_args()

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    min_lon, min_lat, max_lon, max_lat = args.bbox
    min_zoom: int
    max_zoom: int
    min_zoom, max_zoom = args.zoom
    airac_cycle: str = args.airac.strip()
    oaci_prefix: str = args.oaci_prefix.strip()
    show_progress: bool = args.progress

    print(f"🔹 Generating MBTiles for bbox={args.bbox}, zooms={min_zoom}-{max_zoom}, AIRAC={airac_cycle}")

    all_tiles: list[mercantile.Tile] = []
    for zoom in range(min_zoom, max_zoom + 1):
        tiles: list[mercantile.Tile] = list(mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [zoom]))
        print(f"Zoom {zoom}: {len(tiles)} tiles")
        all_tiles.extend(tiles)

    asyncio.run(fetch_all_tiles(all_tiles, args.bbox, airac_cycle, oaci_prefix, min_zoom, max_zoom, show_progress))


if __name__ == "__main__":
    main()
