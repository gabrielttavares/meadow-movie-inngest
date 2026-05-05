import os

import inngest.fast_api
import resend
from fastapi import FastAPI

from src.functions.movie_watched import movie_watched_handler
from src.inngest_client import client

resend.api_key = os.environ.get("RESEND_API_KEY", "")

app = FastAPI(title="Meadow Movie Inngest")

inngest.fast_api.serve(
    app,
    client,
    [movie_watched_handler],
)
