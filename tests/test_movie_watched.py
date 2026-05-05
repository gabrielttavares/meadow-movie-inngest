from unittest.mock import MagicMock, patch

import httpx
import inngest
import pytest
import respx

from src.functions.movie_watched import (
    OMDB_BASE_URL,
    fetch_movie_data,
    send_plot_email,
)
from src.functions.schemas import MovieWatchedEventData

SAMPLE_MOVIE_RESPONSE = {
    "Title": "The Matrix",
    "Year": "1999",
    "Plot": "A computer hacker learns about the true nature of his reality.",
    "Response": "True",
}


# ---------------------------------------------------------------------------
# MovieWatchedEventData validation
# ---------------------------------------------------------------------------


class TestEventValidation:
    def test_valid_event_data(self):
        event = MovieWatchedEventData(movie_title="The Matrix", recipient_email="peter@test.com")
        assert event.movie_title == "The Matrix"
        assert event.recipient_email == "peter@test.com"

    def test_rejects_invalid_email(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="recipient_email"):
            MovieWatchedEventData(movie_title="The Matrix", recipient_email="not-an-email")

    def test_rejects_missing_movie_title(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="movie_title"):
            MovieWatchedEventData(recipient_email="peter@test.com")

    def test_rejects_empty_movie_title(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="movie_title"):
            MovieWatchedEventData(movie_title="", recipient_email="peter@test.com")


# ---------------------------------------------------------------------------
# fetch_movie_data
# ---------------------------------------------------------------------------


class TestFetchMovieData:
    @respx.mock
    async def test_returns_movie_data_on_success(self):
        respx.get(OMDB_BASE_URL).mock(return_value=httpx.Response(200, json=SAMPLE_MOVIE_RESPONSE))

        result = await fetch_movie_data("The Matrix")

        assert result["Title"] == "The Matrix"
        assert result["Plot"] == SAMPLE_MOVIE_RESPONSE["Plot"]

    @respx.mock
    async def test_raises_non_retriable_when_movie_not_found(self):
        not_found_response = {"Response": "False", "Error": "Movie not found!"}
        respx.get(OMDB_BASE_URL).mock(return_value=httpx.Response(200, json=not_found_response))

        with pytest.raises(inngest.NonRetriableError, match="Movie not found"):
            await fetch_movie_data("asdfnonexistentmovie")

    @respx.mock
    async def test_raises_non_retriable_when_plot_is_na(self):
        no_plot_response = {**SAMPLE_MOVIE_RESPONSE, "Plot": "N/A"}
        respx.get(OMDB_BASE_URL).mock(return_value=httpx.Response(200, json=no_plot_response))

        with pytest.raises(inngest.NonRetriableError, match="No plot summary"):
            await fetch_movie_data("The Matrix")

    @respx.mock
    async def test_raises_non_retriable_on_401_unauthorized(self):
        respx.get(OMDB_BASE_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(inngest.NonRetriableError, match="API key is invalid"):
            await fetch_movie_data("The Matrix")

    @respx.mock
    async def test_raises_retriable_error_on_server_error(self):
        respx.get(OMDB_BASE_URL).mock(return_value=httpx.Response(503))

        with pytest.raises(RuntimeError, match="503"):
            await fetch_movie_data("The Matrix")


# ---------------------------------------------------------------------------
# send_plot_email
# ---------------------------------------------------------------------------


class TestSendPlotEmail:
    @patch("src.functions.movie_watched.resend.Emails.send")
    def test_sends_email_with_correct_payload_and_idempotency_key(
        self, mock_resend_send: MagicMock
    ):
        mock_resend_send.return_value = {"id": "email_123"}

        result = send_plot_email(
            "peter@test.com",
            "The Matrix",
            "A computer hacker learns about the true nature of his reality.",
            "run_abc123",
        )

        assert result["id"] == "email_123"

        sent_payload = mock_resend_send.call_args[0][0]
        assert sent_payload["to"] == ["peter@test.com"]
        assert "The Matrix" in sent_payload["subject"]
        assert "computer hacker" in sent_payload["text"]
        assert sent_payload["headers"]["X-Entity-Ref-ID"] == "run_abc123-send-plot-email"

    @patch("src.functions.movie_watched.resend.Emails.send")
    def test_raises_non_retriable_on_validation_error(self, mock_resend_send: MagicMock):
        from resend.exceptions import ValidationError

        mock_resend_send.side_effect = ValidationError("Invalid email", "validation_error", 422)

        with pytest.raises(inngest.NonRetriableError, match="permanent error"):
            send_plot_email("bad-email", "The Matrix", "Some plot", "run_abc123")
