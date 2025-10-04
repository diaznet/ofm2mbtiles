#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
import sqlite3
import mercantile
from datetime import datetime
import argparse
from tqdm import tqdm
from os import path

CONCURRENT_REQUESTS = 10
RETRY_LIMIT = 3
TILE_SIZE = 512


def tms_y(z, y):
    """Convert XYZ Y to TMS Y coordinate.

    Args:
        z (_type_): _description_
        y (_type_): _description_

    Returns:
        _type_: _description_
    """
    return (2**z - 1) - y


def create_mbtiles(path, bbox, min_zoom, max_zoom):
    """_summary_

    Args:
        path (_type_): _description_
        bbox (_type_): _description_
        min_zoom (_type_): _description_
        max_zoom (_type_): _description_

    Returns:
        _type_: _description_
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


async def download_tile(session, url, z, x, y):
    """_summary_

    Args:
        session (_type_): _description_
        url (_type_): _description_
        z (_type_): _description_
        x (_type_): _description_
        y (_type_): _description_

    Returns:
        _type_: _description_
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


async def fetch_all_tiles(tiles, bbox, airac_cycle, min_zoom, max_zoom, show_progress):
    """_summary_

    Args:
        tiles (_type_): _description_
        bbox (_type_): _description_
        airac_cycle (_type_): _description_
        min_zoom (_type_): _description_
        max_zoom (_type_): _description_
        show_progress (_type_): _description_

    Returns:
        _type_: _description_
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mbtiles_file = f"area_{airac_cycle}_z{min_zoom}-{max_zoom}_{timestamp}.mbtiles"
    mbtiles_folder = "mbtiles" + path.sep
    conn = create_mbtiles(mbtiles_folder + mbtiles_file, bbox, min_zoom, max_zoom)
    c = conn.cursor()

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    base_url_template = f"https://nwy-tiles-api.prod.newaydata.com/tiles/{{z}}/{{x}}/{{y}}.png?path={airac_cycle}/aero/latest"

    async with aiohttp.ClientSession() as session:
        async def sem_download(tile):
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


def main():
    """_summary_
    """
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
        "--progress",
        action="store_true",
        help="Show progress bar during downloads"
    )

    args = parser.parse_args()

    min_lon, min_lat, max_lon, max_lat = args.bbox
    min_zoom, max_zoom = args.zoom
    airac_cycle = args.airac.strip()
    show_progress = args.progress

    print(f"🔹 Generating MBTiles for bbox={args.bbox}, zooms={min_zoom}-{max_zoom}, AIRAC={airac_cycle}")

    all_tiles = []
    for zoom in range(min_zoom, max_zoom + 1):
        tiles = list(mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [zoom]))
        print(f"Zoom {zoom}: {len(tiles)} tiles")
        all_tiles.extend(tiles)

    asyncio.run(fetch_all_tiles(all_tiles, args.bbox, airac_cycle, min_zoom, max_zoom, show_progress))


if __name__ == "__main__":
    main()
