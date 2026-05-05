import os
from functools import partial

import httpx
import inngest
import pydantic
import resend

from src.functions.schemas import MovieWatchedEventData, OmdbMovieResponse
from src.inngest_client import client

OMDB_BASE_URL = "https://www.omdbapi.com/"
OMDB_REQUEST_TIMEOUT_SECONDS = 10
RESEND_SENDER_ADDRESS = os.environ.get("RESEND_SENDER_ADDRESS", "onboarding@resend.dev")


async def fetch_movie_data(movie_title: str) -> OmdbMovieResponse:
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

    movie_data: OmdbMovieResponse = response.json()

    if movie_data.get("Response") == "False":
        raise inngest.NonRetriableError(
            message=f"Movie not found: {movie_data.get('Error', 'Unknown error')}"
        )

    if not movie_data.get("Plot") or movie_data["Plot"] == "N/A":
        raise inngest.NonRetriableError(message=f"No plot summary available for '{movie_title}'")

    return movie_data


def send_plot_email(recipient_email: str, movie_title: str, plot_summary: str, run_id: str) -> dict:
    idempotency_key = f"{run_id}-send-plot-email"

    try:
        response = resend.Emails.send(
            {
                "from": RESEND_SENDER_ADDRESS,
                "to": [recipient_email],
                "subject": f"Plot Summary: {movie_title}",
                "text": (
                    f"You recently watched {movie_title}!\n\n"
                    f"Here's the plot summary:\n\n"
                    f"{plot_summary}"
                ),
                "headers": {"X-Entity-Ref-ID": idempotency_key},
            }
        )
    except (
        resend.exceptions.ValidationError,
        resend.exceptions.MissingApiKeyError,
        resend.exceptions.InvalidApiKeyError,
        resend.exceptions.MissingRequiredFieldsError,
    ) as permanent_error:
        raise inngest.NonRetriableError(
            message=f"Resend permanent error (won't retry): {permanent_error}"
        ) from permanent_error

    return response


async def handle_permanent_failure(ctx: inngest.Context) -> None:
    event_data = ctx.event.data or {}
    ctx.logger.error(
        "movie.watched function permanently failed | "
        f"movie_title={event_data.get('movie_title', 'N/A')} | "
        f"recipient_email={event_data.get('recipient_email', 'N/A')} | "
        f"run_id={ctx.run_id}"
    )


@client.create_function(
    fn_id="movie-watched-handler",
    trigger=inngest.TriggerEvent(event="meadow_api/movie.watched"),
    retries=10,
    on_failure=handle_permanent_failure,
)
async def movie_watched_handler(ctx: inngest.Context, step: inngest.Step) -> dict:
    try:
        event_data = MovieWatchedEventData(**(ctx.event.data or {}))
    except pydantic.ValidationError as validation_error:
        raise inngest.NonRetriableError(
            message=f"Invalid event data: {validation_error}"
        ) from validation_error

    movie_data = await step.run(
        "fetch-movie-data",
        partial(fetch_movie_data, event_data.movie_title),
    )

    actual_title = movie_data.get("Title", event_data.movie_title)
    plot_summary = movie_data["Plot"]

    ctx.logger.info(f"Fetched movie data | title='{actual_title}' | year={movie_data.get('Year')}")

    email_response = await step.run(
        "send-plot-email",
        partial(
            send_plot_email,
            event_data.recipient_email,
            actual_title,
            plot_summary,
            ctx.run_id,
        ),
    )

    ctx.logger.info(
        f"Email sent | email_id={email_response.get('id')} | recipient={event_data.recipient_email}"
    )

    return {
        "movie_title": actual_title,
        "recipient_email": event_data.recipient_email,
        "email_id": email_response.get("id"),
    }
