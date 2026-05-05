import os
from functools import partial

import httpx
import inngest

from src.inngest_client import client

OMDB_BASE_URL = "https://www.omdbapi.com/"
OMDB_REQUEST_TIMEOUT_SECONDS = 10


async def fetch_movie_data(movie_title: str) -> dict:
    api_key = os.environ["OMDB_API_KEY"]

    async with httpx.AsyncClient(timeout=OMDB_REQUEST_TIMEOUT_SECONDS) as http_client:
        response = await http_client.get(
            OMDB_BASE_URL,
            params={"apikey": api_key, "t": movie_title},
        )

    if response.is_server_error:
        raise RuntimeError(f"OMDb returned {response.status_code} — transient, will retry")

    if response.status_code == 401:
        raise inngest.NonRetriableError(message="OMDb API key is invalid or missing")

    response.raise_for_status()

    movie_data = response.json()

    if movie_data.get("Response") == "False":
        raise inngest.NonRetriableError(
            message=f"Movie not found: {movie_data.get('Error', 'Unknown error')}"
        )

    if not movie_data.get("Plot") or movie_data["Plot"] == "N/A":
        raise inngest.NonRetriableError(message=f"No plot summary available for '{movie_title}'")

    return movie_data


@client.create_function(
    fn_id="movie-watched-handler",
    trigger=inngest.TriggerEvent(event="meadow_api/movie.watched"),
    retries=10,
)
async def movie_watched_handler(ctx: inngest.Context, step: inngest.Step) -> dict:
    event_data = ctx.event.data or {}

    movie_title = event_data.get("movie_title")
    if not movie_title:
        raise inngest.NonRetriableError(message="Missing 'movie_title' in event data")

    movie_data = await step.run(
        "fetch-movie-data",
        partial(fetch_movie_data, movie_title),
    )

    return {"movie_title": movie_data.get("Title", movie_title), "plot": movie_data["Plot"]}
